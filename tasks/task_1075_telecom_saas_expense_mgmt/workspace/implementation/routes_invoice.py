"""Routes: invoices, line items, disputes, credits."""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, g, request

import core
from core import (db, ApiError, ok, ok_list, guard, get_body, require,
                  check_enum, as_int_nonneg, base_common, touch, serialize,
                  ordered, paginate, find, parse_dt, now_iso, new_id, next_seq,
                  compute_expected_amount, compute_allocation_shares,
                  recompute_invoice_billed_net, lines_of_invoice,
                  open_disputes_on_invoice, WEIGHT_SUM_REQUIRED,
                  MAX_DISPUTE_ROUNDS)

bp = Blueprint("invoice", __name__)

RESPONSE_TYPES = {"FULL_ACCEPT", "PARTIAL", "REJECT"}


def validate_dt(body, field):
    try:
        parse_dt(body[field])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be an ISO 8601 datetime.")
    return body[field]


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@bp.route("/invoices", methods=["POST"])
@guard(["Analyst"])
def create_invoice():
    body = get_body()
    require(body, ["contract_id", "period_start", "period_end"])
    validate_dt(body, "period_start")
    validate_dt(body, "period_end")
    find(db.contracts, body["contract_id"], "ERR_CONTRACT_NOT_FOUND")
    inv = base_common({
        "contract_id": body["contract_id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "status": "RECEIVED",
        "billed_amount_cents": 0,
        "expected_amount_cents": 0,
        "variance_cents": 0,
        "net_amount_cents": 0,
        "balance_due_cents": 0,
        "approved_by_user_id": None,
    })
    db.invoices[inv["id"]] = inv
    return ok(serialize(inv), status=201)


@bp.route("/invoices/<iid>", methods=["GET"])
@guard(core.ALL_ROLES)
def get_invoice(iid):
    inv = find(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    return ok(serialize(inv))


@bp.route("/invoices/<iid>/line-items", methods=["POST"])
@guard(["Analyst"])
def add_line_item(iid):
    body = get_body()
    require(body, ["service_id", "billing_period_start", "billing_period_end",
                   "billed_quantity", "billed_amount_cents"])
    validate_dt(body, "billing_period_start")
    validate_dt(body, "billing_period_end")
    billed_quantity = as_int_nonneg(body, "billed_quantity")
    billed_amount = as_int_nonneg(body, "billed_amount_cents")
    inv = find(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    service = find(db.services, body["service_id"], "ERR_SERVICE_NOT_FOUND")
    # band 8: half-open billing-period overlap for the same service
    a_start = parse_dt(body["billing_period_start"])
    a_end = parse_dt(body["billing_period_end"])
    for other in db.line_items.values():
        if other["service_id"] != service["id"]:
            continue
        b_start = parse_dt(other["billing_period_start"])
        b_end = parse_dt(other["billing_period_end"])
        if a_start < b_end and b_start < a_end:  # half-open; adjacency allowed
            raise ApiError("ERR_BILLING_PERIOD_OVERLAP", 409,
                           "Billing period overlaps an existing line.")
    line = base_common({
        "invoice_id": iid,
        "service_id": service["id"],
        "billing_period_start": body["billing_period_start"],
        "billing_period_end": body["billing_period_end"],
        "billed_quantity": billed_quantity,
        "billed_amount_cents": billed_amount,
        "expected_amount_cents": 0,
        "variance_cents": 0,
        "credited_amount_cents": 0,
        "net_amount_cents": billed_amount,
        "status": "BILLED",
    })
    contract = db.contracts[inv["contract_id"]]
    line["expected_amount_cents"] = compute_expected_amount(
        service, contract, line, "PROVISIONAL")
    db.line_items[line["id"]] = line
    # refresh invoice billed/net (no invoice version bump per endpoint side effects)
    recompute_invoice_billed_net(inv)
    return ok(serialize(line), status=201)


@bp.route("/invoices/<iid>/review", methods=["POST"])
@guard(["Analyst"])
def review_invoice(iid):
    inv = find(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    if inv["status"] != "RECEIVED":
        raise ApiError("ERR_INVOICE_NOT_REVIEWABLE", 409, "Invoice not RECEIVED.")
    contract = db.contracts[inv["contract_id"]]
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409, "Parent contract not ACTIVE.")
    lines = lines_of_invoice(iid)
    for line in lines:
        service = db.services[line["service_id"]]
        final_expected = compute_expected_amount(service, contract, line, "FINAL")
        line["expected_amount_cents"] = final_expected
        line["variance_cents"] = line["billed_amount_cents"] - final_expected
        line["net_amount_cents"] = line["billed_amount_cents"] - line["credited_amount_cents"]
    billed = sum(li["billed_amount_cents"] for li in lines)
    expected = sum(li["expected_amount_cents"] for li in lines)
    credited = sum(li["credited_amount_cents"] for li in lines)
    inv["billed_amount_cents"] = billed
    inv["expected_amount_cents"] = expected
    inv["variance_cents"] = billed - expected
    inv["net_amount_cents"] = billed - credited
    inv["balance_due_cents"] = billed - credited
    inv["status"] = "UNDER_REVIEW"
    touch(inv)
    return ok(serialize(inv))


@bp.route("/invoices/<iid>/approve", methods=["POST"])
@guard(["FinanceApprover"])
def approve_invoice(iid):
    inv = find(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    if inv["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice not UNDER_REVIEW.")
    contract = db.contracts[inv["contract_id"]]
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409, "Parent contract not ACTIVE.")
    inv["status"] = "APPROVED"
    inv["approved_by_user_id"] = g.user_id
    touch(inv)
    return ok(serialize(inv))


@bp.route("/invoices/<iid>/pay", methods=["POST"])
@guard(["FinanceApprover"])
def pay_invoice(iid):
    inv = find(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    if inv["status"] != "APPROVED":
        raise ApiError("ERR_INVOICE_NOT_APPROVED", 409, "Invoice not APPROVED.")
    if g.user_id == inv["approved_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "Payer must differ from approver.")
    inv["status"] = "PAID"
    inv["balance_due_cents"] = 0
    touch(inv)
    return ok(serialize(inv))


# ---------------------------------------------------------------------------
# Line items (reads + dispute/allocation creation)
# ---------------------------------------------------------------------------
@bp.route("/invoice-line-items/<lid>", methods=["GET"])
@guard(core.ALL_ROLES)
def get_line_item(lid):
    line = find(db.line_items, lid, "ERR_LINE_ITEM_NOT_FOUND")
    return ok(serialize(line))


@bp.route("/invoice-line-items", methods=["GET"])
@guard(core.ALL_ROLES)
def list_line_items():
    invoice_id = request.args.get("invoice_id")
    service_id = request.args.get("service_id")
    items = list(db.line_items.values())
    if invoice_id:
        items = [li for li in items if li["invoice_id"] == invoice_id]
    if service_id:
        items = [li for li in items if li["service_id"] == service_id]
    items = ordered(items)
    page, meta = paginate(items)
    return ok_list([serialize(li) for li in page], meta)


@bp.route("/invoice-line-items/<lid>/disputes", methods=["GET"])
@guard(core.ALL_ROLES)
def list_line_disputes(lid):
    find(db.line_items, lid, "ERR_LINE_ITEM_NOT_FOUND")
    items = ordered([d for d in db.disputes.values()
                     if d["invoice_line_item_id"] == lid])
    page, meta = paginate(items)
    return ok_list([serialize(d) for d in page], meta)


@bp.route("/invoice-line-items/<lid>/allocations", methods=["GET"])
@guard(core.ALL_ROLES)
def list_line_allocations(lid):
    find(db.line_items, lid, "ERR_LINE_ITEM_NOT_FOUND")
    items = ordered([a for a in db.allocations.values()
                     if a["invoice_line_item_id"] == lid])
    page, meta = paginate(items)
    return ok_list([serialize(a) for a in page], meta)


@bp.route("/invoice-line-items/<lid>/disputes", methods=["POST"])
@guard(["Analyst"])
def open_dispute(lid):
    body = get_body()
    require(body, ["disputed_amount_cents", "claimed_credit_cents"])
    disputed_amount = as_int_nonneg(body, "disputed_amount_cents")
    claimed_credit = as_int_nonneg(body, "claimed_credit_cents")
    reason = body.get("reason")
    line = find(db.line_items, lid, "ERR_LINE_ITEM_NOT_FOUND")
    inv = db.invoices[line["invoice_id"]]
    # band 5: line disputable
    if line["status"] != "BILLED" or inv["status"] not in ("UNDER_REVIEW", "DISPUTED"):
        raise ApiError("ERR_LINE_NOT_DISPUTABLE", 409, "Line is not disputable.")
    # band 9: fiscal ceiling
    if claimed_credit > line["billed_amount_cents"]:
        raise ApiError("ERR_CREDIT_EXCEEDS_BILLED", 422,
                       "Claimed credit exceeds billed amount.")
    d = base_common({
        "invoice_line_item_id": lid,
        "disputed_amount_cents": disputed_amount,
        "claimed_credit_cents": claimed_credit,
        "offered_credit_cents": 0,
        "recovered_credit_cents": 0,
        "response_type": "NONE",
        "round_count": 0,
        "reason": reason,
        "status": "SUBMITTED",
    })
    db.disputes[d["id"]] = d
    line["status"] = "DISPUTED"
    touch(line)
    if inv["status"] == "UNDER_REVIEW":
        inv["status"] = "DISPUTED"
        touch(inv)
    return ok(serialize(d), status=201)


@bp.route("/invoice-line-items/<lid>/allocations", methods=["POST"])
@guard(["Analyst"])
def create_allocations(lid):
    body = get_body()
    require(body, ["allocations"])
    specs_in = body["allocations"]
    if not isinstance(specs_in, list):
        raise ApiError("ERR_VALIDATION", 422, "allocations must be an array.")
    parsed = []
    for entry in specs_in:
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION", 422, "allocation entry must be an object.")
        if "cost_center_id" not in entry or entry["cost_center_id"] is None:
            raise ApiError("ERR_VALIDATION", 422, "Missing cost_center_id.")
        if "weight_pct" not in entry or entry["weight_pct"] is None:
            raise ApiError("ERR_VALIDATION", 422, "Missing weight_pct.")
        w = entry["weight_pct"]
        if isinstance(w, bool) or not isinstance(w, (int, float)):
            raise ApiError("ERR_VALIDATION", 422, "weight_pct must be a number.")
        try:
            wdec = Decimal(str(w))
        except (InvalidOperation, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "weight_pct must be a number.")
        if wdec < 0 or wdec > 100:
            raise ApiError("ERR_VALIDATION", 422, "weight_pct must be within [0, 100].")
        parsed.append({"cost_center_id": entry["cost_center_id"],
                       "weight": wdec, "raw_weight": w})
    line = find(db.line_items, lid, "ERR_LINE_ITEM_NOT_FOUND")
    for p in parsed:
        cc = find(db.cost_centers, p["cost_center_id"], "ERR_COST_CENTER_NOT_FOUND")
        p["cc_seq"] = cc["_seq"]
    # band 8: weights must sum to exactly 100.00
    total_weight = sum((p["weight"] for p in parsed), Decimal(0))
    if total_weight != WEIGHT_SUM_REQUIRED:
        raise ApiError("ERR_INVALID_WEIGHT_SUM", 422,
                       "Allocation weights must sum to exactly 100.00.")
    specs = [{"weight": p["weight"], "cc_seq": p["cc_seq"], "ref": i}
             for i, p in enumerate(parsed)]
    shares = compute_allocation_shares(line["net_amount_cents"], specs)
    amount_by_ref = {ref: amt for ref, amt in shares}
    created = []
    for i, p in enumerate(parsed):
        a = base_common({
            "invoice_line_item_id": lid,
            "cost_center_id": p["cost_center_id"],
            "weight_pct": p["raw_weight"],
            "amount_cents": amount_by_ref[i],
            "status": "DRAFT",
        })
        db.allocations[a["id"]] = a
        created.append(serialize(a))
    return core.created_list(created)


# ---------------------------------------------------------------------------
# Dispute actions
# ---------------------------------------------------------------------------
@bp.route("/disputes/<did>/respond", methods=["POST"])
@guard(["Vendor"])
def respond_dispute(did):
    body = get_body()
    require(body, ["response_type", "offered_credit_cents"])
    check_enum(body["response_type"], RESPONSE_TYPES, "response_type")
    offered = as_int_nonneg(body, "offered_credit_cents")
    d = find(db.disputes, did, "ERR_DISPUTE_NOT_FOUND")
    if d["status"] not in ("SUBMITTED", "RESUBMITTED"):
        raise ApiError("ERR_DISPUTE_NOT_RESPONDED", 409,
                       "Dispute not awaiting a vendor response.")
    if offered > d["claimed_credit_cents"]:
        raise ApiError("ERR_OFFER_EXCEEDS_CLAIM", 422,
                       "Offered credit exceeds claimed credit.")
    d["response_type"] = body["response_type"]
    d["offered_credit_cents"] = offered
    d["status"] = "VENDOR_RESPONDED"
    touch(d)
    return ok(serialize(d))


@bp.route("/disputes/<did>/resubmit", methods=["POST"])
@guard(["Analyst"])
def resubmit_dispute(did):
    body = get_body()
    require(body, ["claimed_credit_cents"])
    claimed = as_int_nonneg(body, "claimed_credit_cents")
    d = find(db.disputes, did, "ERR_DISPUTE_NOT_FOUND")
    if d["status"] != "VENDOR_RESPONDED":
        raise ApiError("ERR_DISPUTE_NOT_RESPONDED", 409,
                       "Dispute not in VENDOR_RESPONDED.")
    if d["round_count"] >= MAX_DISPUTE_ROUNDS:
        raise ApiError("ERR_MAX_ROUNDS_EXCEEDED", 409, "Max dispute rounds reached.")
    line = db.line_items[d["invoice_line_item_id"]]
    if claimed > line["billed_amount_cents"]:
        raise ApiError("ERR_CREDIT_EXCEEDS_BILLED", 422,
                       "Claimed credit exceeds billed amount.")
    d["claimed_credit_cents"] = claimed
    d["round_count"] += 1
    d["status"] = "RESUBMITTED"
    touch(d)
    return ok(serialize(d))


@bp.route("/disputes/<did>/accept", methods=["POST"])
@guard(["Analyst"])
def accept_dispute(did):
    d = find(db.disputes, did, "ERR_DISPUTE_NOT_FOUND")
    if d["status"] != "VENDOR_RESPONDED":
        raise ApiError("ERR_DISPUTE_NOT_RESPONDED", 409,
                       "Dispute not in VENDOR_RESPONDED.")
    amount = d["offered_credit_cents"]
    line = db.line_items[d["invoice_line_item_id"]]
    inv = db.invoices[line["invoice_id"]]
    contract = db.contracts[inv["contract_id"]]
    # dispute -> ACCEPTED
    d["recovered_credit_cents"] = amount
    d["status"] = "ACCEPTED"
    touch(d)
    # create Credit ledger entry (append-only: id + created_at only)
    credit = {
        "id": new_id(),
        "dispute_id": d["id"],
        "invoice_line_item_id": line["id"],
        "amount_cents": amount,
        "status": "ISSUED",
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    db.credits[credit["id"]] = credit
    # line DISPUTED -> CREDITED
    line["credited_amount_cents"] += amount
    line["net_amount_cents"] = line["billed_amount_cents"] - line["credited_amount_cents"]
    line["status"] = "CREDITED"
    touch(line)
    # contract recovered ledger
    contract["total_recovered_cents"] += amount
    touch(contract)
    # allocations on the line (DRAFT or POSTED) -> REVERSED
    for a in db.allocations.values():
        if a["invoice_line_item_id"] == line["id"] and a["status"] in ("DRAFT", "POSTED"):
            a["status"] = "REVERSED"
            touch(a)
    # invoice: recompute net/balance; revert DISPUTED -> UNDER_REVIEW if no open disputes
    recompute_invoice_billed_net(inv)
    inv["balance_due_cents"] = inv["net_amount_cents"]
    if not open_disputes_on_invoice(inv["id"]) and inv["status"] == "DISPUTED":
        inv["status"] = "UNDER_REVIEW"
    touch(inv)
    return ok(serialize(d))


@bp.route("/disputes/<did>/withdraw", methods=["POST"])
@guard(["Analyst"])
def withdraw_dispute(did):
    d = find(db.disputes, did, "ERR_DISPUTE_NOT_FOUND")
    if d["status"] not in ("SUBMITTED", "VENDOR_RESPONDED", "RESUBMITTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Dispute cannot be withdrawn.")
    line = db.line_items[d["invoice_line_item_id"]]
    inv = db.invoices[line["invoice_id"]]
    d["status"] = "WITHDRAWN"
    touch(d)
    # line DISPUTED -> BILLED (no change to credited/net)
    line["status"] = "BILLED"
    touch(line)
    # invoice revert if no open disputes remain
    if not open_disputes_on_invoice(inv["id"]) and inv["status"] == "DISPUTED":
        inv["status"] = "UNDER_REVIEW"
        recompute_invoice_billed_net(inv)
        inv["balance_due_cents"] = inv["net_amount_cents"]
        touch(inv)
    return ok(serialize(d))


# ---------------------------------------------------------------------------
# Credits
# ---------------------------------------------------------------------------
@bp.route("/credits/<cid>", methods=["GET"])
@guard(core.ALL_ROLES)
def get_credit(cid):
    c = find(db.credits, cid, "ERR_CREDIT_NOT_FOUND")
    return ok(serialize(c))


@bp.route("/credits", methods=["GET"])
@guard(core.ALL_ROLES)
def list_credits():
    dispute_id = request.args.get("dispute_id")
    line_item_id = request.args.get("invoice_line_item_id")
    items = list(db.credits.values())
    if dispute_id:
        items = [c for c in items if c["dispute_id"] == dispute_id]
    if line_item_id:
        items = [c for c in items if c["invoice_line_item_id"] == line_item_id]
    items = ordered(items)
    page, meta = paginate(items)
    return ok_list([serialize(c) for c in page], meta)
