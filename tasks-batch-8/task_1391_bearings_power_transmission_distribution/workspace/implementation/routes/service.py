"""Warranty claims, return authorizations, service shops, service referrals."""

from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

import domain
from db import store
from errors import err
from helpers import (FAMILIES, dec, get_body, new_id, now, req_enum, req_int,
                     req_str, rhu, stamp_new, touch)
from middleware import require_any, require_roles
from response import ok, ok_list, paginate
from serialize import serialize, serialize_list
from domain import (OBSOLETE_WRITE_DOWN_PCT, REFERRAL_FEE_CAP_CENTS,
                    REFERRAL_FEE_PCT, RESTOCK_FEE_PCT, RMA_WINDOW_DAYS)

bp = Blueprint("service", __name__)

FAILURE_MODES = ("FATIGUE", "CONTAMINATION", "MISALIGNMENT", "LUBRICATION",
                 "BRINELLING", "OTHER")


def get_claim(cid):
    c = store.claims.get(cid)
    if c is None:
        raise err("ERR_CLAIM_NOT_FOUND", f"warranty claim {cid} not found")
    return c


def get_return(rid):
    r = store.returns.get(rid)
    if r is None:
        raise err("ERR_RETURN_NOT_FOUND", f"return authorization {rid} not found")
    return r


def get_shop(sid):
    s = store.shops.get(sid)
    if s is None:
        raise err("ERR_SHOP_NOT_FOUND", f"service shop {sid} not found")
    return s


def get_referral(rid):
    r = store.referrals.get(rid)
    if r is None:
        raise err("ERR_REFERRAL_NOT_FOUND", f"service referral {rid} not found")
    return r


# ---------------------------------------------------------- warranty claims --

@bp.route("/motion/warranty-claims", methods=["POST"])
@require_roles("WarrantyAnalyst")
def create_claim(user_id, role):
    body = get_body()
    # body FK existence (priority 3)
    product_id = req_str(body, "product_id") if "product_id" in body else None
    order_line_id = body.get("order_line_id")
    consumption_id = body.get("consumption_id")
    if product_id is not None and product_id not in store.products:
        raise err("ERR_PRODUCT_NOT_FOUND", f"product {product_id} not found")
    if order_line_id is not None and order_line_id not in store.order_lines:
        raise err("ERR_ORDER_LINE_NOT_FOUND", f"order line {order_line_id} not found")
    if consumption_id is not None and consumption_id not in store.consumptions:
        raise err("ERR_CONSUMPTION_NOT_FOUND", f"consumption {consumption_id} not found")
    # shape (priority 7)
    if product_id is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: product_id")
    if (order_line_id is None) == (consumption_id is None):
        raise err("ERR_CLAIM_REFERENCE_INVALID",
                  "exactly one of order_line_id / consumption_id is required")
    failure = req_enum(body, "failure_mode", FAILURE_MODES)
    hours = req_int(body, "operating_hours", minimum=0)
    qty = req_int(body, "qty", minimum=1)
    # referential (priority 9): qty may not exceed source qty
    if order_line_id is not None:
        source_qty = store.order_lines[order_line_id]["qty"]
    else:
        source_qty = store.consumptions[consumption_id]["qty"]
    if qty > source_qty:
        raise err("ERR_CLAIM_QTY_EXCEEDS_SOURCE", "claim qty exceeds source qty")
    rec = stamp_new({
        "id": new_id(),
        "product_id": product_id,
        "order_line_id": order_line_id,
        "consumption_id": consumption_id,
        "filed_by": user_id,
        "failure_mode": failure,
        "operating_hours": hours,
        "qty": qty,
        "verdict": "NONE",
        "verdict_by": None,
        "coverage_pct": 0,
        "credit_amount_cents": 0,
        "status": "SUBMITTED",
    })
    store.claims[rec["id"]] = rec
    return ok(serialize("WarrantyClaim", rec), 201)


@bp.route("/motion/warranty-claims", methods=["GET"])
@require_any
def list_claims(user_id, role):
    items = list(store.claims.values())
    q = request.args
    for param in ("product_id", "order_line_id", "consumption_id", "status"):
        if q.get(param) is not None:
            items = [c for c in items if c[param] == q[param]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("WarrantyClaim", page), limit, offset, total)


@bp.route("/motion/warranty-claims/<cid>", methods=["GET"])
@require_any
def get_claim_route(user_id, role, cid):
    return ok(serialize("WarrantyClaim", get_claim(cid)))


@bp.route("/motion/warranty-claims/<cid>/begin-analysis", methods=["POST"])
@require_roles("QualityEngineer")
def begin_analysis(user_id, role, cid):
    c = get_claim(cid)
    if c["status"] != "SUBMITTED":
        raise err("ERR_CLAIM_NOT_SUBMITTED", "begin-analysis requires claim SUBMITTED")
    c["status"] = "UNDER_ANALYSIS"
    touch(c)
    return ok(serialize("WarrantyClaim", c))


@bp.route("/motion/warranty-claims/<cid>/request-info", methods=["POST"])
@require_roles("QualityEngineer")
def request_info(user_id, role, cid):
    c = get_claim(cid)
    if c["status"] != "UNDER_ANALYSIS":
        raise err("ERR_CLAIM_NOT_UNDER_ANALYSIS", "request-info requires UNDER_ANALYSIS")
    c["status"] = "SUBMITTED"
    touch(c)
    return ok(serialize("WarrantyClaim", c))


@bp.route("/motion/warranty-claims/<cid>/verdict", methods=["POST"])
@require_roles("QualityEngineer")
def render_verdict(user_id, role, cid):
    c = get_claim(cid)
    # state (priority 5) before SoD (priority 6)
    if c["status"] != "UNDER_ANALYSIS":
        raise err("ERR_CLAIM_NOT_UNDER_ANALYSIS", "verdict requires UNDER_ANALYSIS")
    if user_id == c["filed_by"]:
        raise err("ERR_WARRANTY_SOD_VERDICT",
                  "verdict user must differ from the claim filer")
    body = get_body()
    verdict = req_enum(body, "verdict", ("CONFIRMED_DEFECT", "MISAPPLICATION", "WEAR_OUT"))
    if verdict == "CONFIRMED_DEFECT":
        # referential (priority 9): source must be final
        if c["order_line_id"] is not None:
            line = store.order_lines[c["order_line_id"]]
            if line["sourcing_status"] != "SHIPPED":
                raise err("ERR_CLAIM_SOURCE_NOT_FINAL", "order line must be SHIPPED")
            source_unit = line["unit_price_cents"]
        else:
            cons = store.consumptions[c["consumption_id"]]
            if cons["status"] not in ("INVOICED", "REPORTED"):
                raise err("ERR_CLAIM_SOURCE_NOT_FINAL",
                          "consumption must be INVOICED or REPORTED")
            if cons["status"] == "INVOICED":
                source_unit = cons["unit_price_cents"]
            else:
                ag = store.agreements[cons["agreement_id"]]
                source_unit = ag["pinned_unit_price_cents"]
        hours = c["operating_hours"]
        if hours < 2000:
            coverage = 1.0
        elif hours < 5000:
            coverage = 0.5
        else:
            coverage = 0.25
        c["coverage_pct"] = coverage
        c["credit_amount_cents"] = rhu(dec(source_unit) * c["qty"] * dec(coverage))
        c["status"] = "APPROVED"
    else:
        c["coverage_pct"] = 0
        c["credit_amount_cents"] = 0
        c["status"] = "DENIED"
    c["verdict"] = verdict
    c["verdict_by"] = user_id
    touch(c)
    return ok(serialize("WarrantyClaim", c))


@bp.route("/motion/warranty-claims/<cid>/issue-credit", methods=["POST"])
@require_roles("BranchManager")
def issue_claim_credit(user_id, role, cid):
    c = get_claim(cid)
    if c["status"] != "APPROVED":
        raise err("ERR_CLAIM_NOT_APPROVED", "issue-credit requires claim APPROVED")
    c["status"] = "CREDIT_ISSUED"
    touch(c)
    # consignment cross-effect: full-qty claim credits the consumption (hop 1),
    # agreement quantities recompute excluding CREDITED (hop 2); the
    # receivables adjustment folds into the claim credit (no double count).
    if c["consumption_id"] is not None:
        cons = store.consumptions.get(c["consumption_id"])
        if cons is not None and cons["status"] == "INVOICED" and cons["qty"] == c["qty"]:
            cons["status"] = "CREDITED"
            touch(cons)
            ag = store.agreements.get(cons["agreement_id"])
            if ag is not None:
                touch(ag)
    return ok(serialize("WarrantyClaim", c))


# ------------------------------------------------------------- returns -----

@bp.route("/motion/return-authorizations", methods=["POST"])
@require_roles("CustomerPlant", "CounterSalesRep")
def create_return(user_id, role):
    body = get_body()
    customer_id = req_str(body, "customer_id") if "customer_id" in body else None
    product_id = req_str(body, "product_id") if "product_id" in body else None
    branch_id = req_str(body, "branch_id") if "branch_id" in body else None
    # body FK existence (priority 3)
    for val, coll, eid in (
        (customer_id, store.customers, "ERR_CUSTOMER_NOT_FOUND"),
        (product_id, store.products, "ERR_PRODUCT_NOT_FOUND"),
        (branch_id, store.branches, "ERR_BRANCH_NOT_FOUND"),
    ):
        if val is not None and val not in coll:
            raise err(eid, f"referenced resource {val} not found")
    # identity (priority 4)
    if role == "CustomerPlant" and customer_id is not None and customer_id != user_id:
        raise err("ERR_IDENTITY_MISMATCH",
                  "CustomerPlant may request returns only for its own account")
    # shape (priority 7)
    if customer_id is None or product_id is None or branch_id is None:
        raise err("ERR_INVALID_REQUEST", "customer_id, product_id, branch_id are required")
    qty = req_int(body, "qty", minimum=1)
    condition = req_enum(body, "condition", ("SURPLUS", "OBSOLETE"))
    original = req_int(body, "original_unit_price_cents", minimum=0)
    rec = stamp_new({
        "id": new_id(),
        "customer_id": customer_id,
        "product_id": product_id,
        "branch_id": branch_id,
        "qty": qty,
        "condition": condition,
        "original_unit_price_cents": original,
        "requested_by": user_id,
        "approved_by": None,
        "eligible_credit_cents": 0,
        "write_down_cents": 0,
        "offset_applied_cents": 0,
        "credit_memo_cents": 0,
        "received_qty": 0,
        "approved_at": None,
        "status": "REQUESTED",
    })
    store.returns[rec["id"]] = rec
    return ok(serialize("ReturnAuthorization", rec), 201)


@bp.route("/motion/return-authorizations", methods=["GET"])
@require_any
def list_returns(user_id, role):
    items = list(store.returns.values())
    q = request.args
    for param in ("customer_id", "product_id", "branch_id", "status"):
        if q.get(param) is not None:
            items = [r for r in items if r[param] == q[param]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("ReturnAuthorization", page), limit, offset, total)


@bp.route("/motion/return-authorizations/<rid>", methods=["GET"])
@require_any
def get_return_route(user_id, role, rid):
    return ok(serialize("ReturnAuthorization", get_return(rid)))


def _cumulative_shipped(customer_id, product_id):
    total = 0
    for line in store.order_lines.values():
        if line["product_id"] != product_id or line["sourcing_status"] != "SHIPPED":
            continue
        order = store.orders.get(line["order_id"])
        if order and order["customer_id"] == customer_id:
            total += line["qty"]
    return total


@bp.route("/motion/return-authorizations/<rid>/approve", methods=["POST"])
@require_roles("BranchManager")
def approve_return(user_id, role, rid):
    r = get_return(rid)
    # state (priority 5), then SoD (priority 6), then referential (priority 9)
    if r["status"] != "REQUESTED":
        raise err("ERR_RETURN_NOT_REQUESTED", "approve requires return REQUESTED")
    if user_id == r["requested_by"]:
        raise err("ERR_RETURN_SOD_APPROVAL", "approver must differ from requester")
    if r["qty"] > _cumulative_shipped(r["customer_id"], r["product_id"]):
        raise err("ERR_RETURN_QTY_EXCEEDS_SHIPPED",
                  "return qty exceeds customer's cumulative shipped qty")
    r["approved_by"] = user_id
    r["approved_at"] = now()
    r["status"] = "APPROVED"
    touch(r)
    return ok(serialize("ReturnAuthorization", r))


@bp.route("/motion/return-authorizations/<rid>/reject", methods=["POST"])
@require_roles("BranchManager")
def reject_return(user_id, role, rid):
    r = get_return(rid)
    if r["status"] != "REQUESTED":
        raise err("ERR_RETURN_NOT_REQUESTED", "reject requires return REQUESTED")
    if user_id == r["requested_by"]:
        raise err("ERR_RETURN_SOD_APPROVAL", "rejector must differ from requester")
    r["status"] = "REJECTED"
    touch(r)
    return ok(serialize("ReturnAuthorization", r))


@bp.route("/motion/return-authorizations/<rid>/receive", methods=["POST"])
@require_roles("BranchManager")
def receive_return(user_id, role, rid):
    r = get_return(rid)
    # state (priority 5)
    if r["status"] != "APPROVED":
        raise err("ERR_RETURN_NOT_APPROVED", "receive requires return APPROVED")
    body = get_body()
    # shape (priority 7): field present and integer
    received = req_int(body, "received_qty")
    # temporal (priority 8): within RMA window
    if now() > r["approved_at"] + timedelta(days=RMA_WINDOW_DAYS):
        raise err("ERR_RMA_WINDOW_EXPIRED", "receipt after approved_at + 30 days")
    # referential (priority 9): 1..authorized qty
    if received < 1 or received > r["qty"]:
        raise err("ERR_INVALID_RECEIVED_QTY", "received_qty must be within 1..qty")
    product = store.products[r["product_id"]]
    base = received * min(r["original_unit_price_cents"], product["list_price_cents"])
    r["eligible_credit_cents"] = rhu(dec(base) * (Decimal(1) - RESTOCK_FEE_PCT))
    r["write_down_cents"] = (
        rhu(dec(r["eligible_credit_cents"]) * OBSOLETE_WRITE_DOWN_PCT)
        if r["condition"] == "OBSOLETE" else 0
    )
    r["received_qty"] = received
    # restock: SURPLUS of an ACTIVE product lands back on the shelf
    if r["condition"] == "SURPLUS" and product["status"] == "ACTIVE":
        stock = domain.find_stock(r["branch_id"], r["product_id"])
        if stock is not None:
            stock["on_hand_qty"] += received
            touch(stock)
    r["status"] = "RECEIVED"
    touch(r)
    return ok(serialize("ReturnAuthorization", r))


@bp.route("/motion/return-authorizations/<rid>/issue-credit", methods=["POST"])
@require_roles("BranchManager")
def issue_return_credit(user_id, role, rid):
    r = get_return(rid)
    if r["status"] != "RECEIVED":
        raise err("ERR_RETURN_NOT_RECEIVED", "issue-credit requires return RECEIVED")
    nettable = r["eligible_credit_cents"] - r["write_down_cents"]
    # bucket 1: outstanding consignment invoices of this customer, oldest first
    outstanding = []
    for c in store.consumptions.values():
        if c["status"] != "INVOICED":
            continue
        ag = store.agreements.get(c["agreement_id"])
        if not ag or ag["customer_id"] != r["customer_id"]:
            continue
        due = c["billed_amount_cents"] - c["offset_applied_cents"]
        if due > 0:
            outstanding.append(c)
    outstanding.sort(key=lambda c: (c["created_at"], c["reported_at"], c["_seq"]))
    applied = 0
    for c in outstanding:
        if applied >= nettable:
            break
        due = c["billed_amount_cents"] - c["offset_applied_cents"]
        take = min(due, nettable - applied)
        c["offset_applied_cents"] += take
        touch(c)
        applied += take
    r["offset_applied_cents"] = applied
    r["credit_memo_cents"] = nettable - applied
    r["status"] = "CREDIT_ISSUED"
    touch(r)
    return ok(serialize("ReturnAuthorization", r))


# ---------------------------------------------------------------- shops ----

@bp.route("/motion/service-shops", methods=["POST"])
@require_roles("SystemAdmin")
def create_shop(user_id, role):
    body = get_body()
    name = req_str(body, "name")
    caps = body.get("capabilities")
    if not isinstance(caps, list) or any(not isinstance(x, str) or x not in FAMILIES for x in caps):
        raise err("ERR_INVALID_REQUEST", "capabilities must be a list of product families")
    region = req_str(body, "region")
    rate = req_int(body, "labor_rate_cents", minimum=0)
    rec = stamp_new({
        "id": new_id(),
        "name": name,
        "capabilities": list(caps),
        "region": region,
        "labor_rate_cents": rate,
        "status": "ACTIVE",
    })
    store.shops[rec["id"]] = rec
    return ok(serialize("ServiceShop", rec), 201)


@bp.route("/motion/service-shops", methods=["GET"])
@require_any
def list_shops(user_id, role):
    items = list(store.shops.values())
    q = request.args
    if q.get("region") is not None:
        items = [s for s in items if s["region"] == q["region"]]
    if q.get("capability") is not None:
        items = [s for s in items if q["capability"] in s["capabilities"]]
    if q.get("status") is not None:
        items = [s for s in items if s["status"] == q["status"]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("ServiceShop", page), limit, offset, total)


@bp.route("/motion/service-shops/<sid>", methods=["GET"])
@require_any
def get_shop_route(user_id, role, sid):
    return ok(serialize("ServiceShop", get_shop(sid)))


@bp.route("/motion/service-shops/<sid>", methods=["PATCH"])
@require_roles("SystemAdmin")
def patch_shop(user_id, role, sid):
    s = get_shop(sid)
    body = get_body()
    s["status"] = req_enum(body, "status", ("ACTIVE", "INACTIVE"))
    touch(s)
    return ok(serialize("ServiceShop", s))


# ------------------------------------------------------------- referrals ---

def _new_referral(claim_id, region, declined):
    rec = stamp_new({
        "id": new_id(),
        "warranty_claim_id": claim_id,
        "service_shop_id": None,
        "region": region,
        "quoted_amount_cents": None,
        "referral_fee_cents": 0,
        "declined_shop_ids": list(declined),
        "status": "OPEN",
    })
    return rec


@bp.route("/motion/service-referrals", methods=["POST"])
@require_roles("WarrantyAnalyst")
def create_referral(user_id, role):
    body = get_body()
    claim_id = req_str(body, "warranty_claim_id") if "warranty_claim_id" in body else None
    if claim_id is not None and claim_id not in store.claims:
        raise err("ERR_CLAIM_NOT_FOUND", f"warranty claim {claim_id} not found")
    if claim_id is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: warranty_claim_id")
    region = req_str(body, "region")
    claim = store.claims[claim_id]
    # referential (priority 9): verdict then selector eligibility
    if claim["verdict"] != "MISAPPLICATION":
        raise err("ERR_REFERRAL_VERDICT_NOT_MISAPPLICATION",
                  "referral requires claim verdict MISAPPLICATION")
    declined = domain.chain_declined_shop_ids(claim_id)
    shop = domain.select_shop(claim, region, declined)
    if shop is None:
        raise err("ERR_NO_ELIGIBLE_SHOP", "no eligible shop for this referral")
    rec = _new_referral(claim_id, region, declined)
    rec["service_shop_id"] = shop["id"]
    store.referrals[rec["id"]] = rec
    return ok(serialize("ServiceReferral", rec), 201)


@bp.route("/motion/service-referrals", methods=["GET"])
@require_any
def list_referrals(user_id, role):
    items = list(store.referrals.values())
    q = request.args
    for param in ("warranty_claim_id", "service_shop_id", "status"):
        if q.get(param) is not None:
            items = [r for r in items if r[param] == q[param]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("ServiceReferral", page), limit, offset, total)


@bp.route("/motion/service-referrals/<rid>", methods=["GET"])
@require_any
def get_referral_route(user_id, role, rid):
    return ok(serialize("ServiceReferral", get_referral(rid)))


def _check_shop_identity(user_id, referral):
    if user_id != referral["service_shop_id"]:
        raise err("ERR_REFERRAL_SHOP_MISMATCH",
                  "acting ServiceShop id does not equal referral.service_shop_id")


@bp.route("/motion/service-referrals/<rid>/accept", methods=["POST"])
@require_roles("ServiceShop")
def accept_referral(user_id, role, rid):
    r = get_referral(rid)
    _check_shop_identity(user_id, r)  # identity (priority 4) before state
    if r["status"] != "OPEN":
        raise err("ERR_REFERRAL_NOT_OPEN", "accept requires referral OPEN")
    body = get_body()
    quote = req_int(body, "quoted_amount_cents", minimum=1)
    r["quoted_amount_cents"] = quote
    r["status"] = "ACCEPTED"
    touch(r)
    return ok(serialize("ServiceReferral", r))


@bp.route("/motion/service-referrals/<rid>/decline", methods=["POST"])
@require_roles("ServiceShop")
def decline_referral(user_id, role, rid):
    r = get_referral(rid)
    _check_shop_identity(user_id, r)
    if r["status"] != "OPEN":
        raise err("ERR_REFERRAL_NOT_OPEN", "decline requires referral OPEN")
    r["status"] = "DECLINED"
    declined = domain.chain_declined_shop_ids(r["warranty_claim_id"])
    # chain now includes this shop
    if r["service_shop_id"] not in declined:
        declined.append(r["service_shop_id"])
    r["declined_shop_ids"] = list(declined)
    touch(r)
    # immediate successor via selector excluding all decliners; none if empty
    claim = store.claims[r["warranty_claim_id"]]
    shop = domain.select_shop(claim, r["region"], declined)
    if shop is not None:
        nxt = _new_referral(r["warranty_claim_id"], r["region"], declined)
        nxt["service_shop_id"] = shop["id"]
        store.referrals[nxt["id"]] = nxt
    return ok(serialize("ServiceReferral", r))


@bp.route("/motion/service-referrals/<rid>/complete", methods=["POST"])
@require_roles("ServiceShop")
def complete_referral(user_id, role, rid):
    r = get_referral(rid)
    _check_shop_identity(user_id, r)
    if r["status"] != "ACCEPTED":
        raise err("ERR_REFERRAL_NOT_ACCEPTED", "complete requires referral ACCEPTED")
    r["referral_fee_cents"] = min(
        rhu(dec(r["quoted_amount_cents"]) * REFERRAL_FEE_PCT),
        REFERRAL_FEE_CAP_CENTS,
    )
    r["status"] = "COMPLETED"
    touch(r)
    return ok(serialize("ServiceReferral", r))
