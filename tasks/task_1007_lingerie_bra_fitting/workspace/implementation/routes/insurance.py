"""InsuranceClaim endpoints for mastectomy purchases (PRD §3.6)."""
from flask import Blueprint, g

import store
import api as h
import calc
import serialize as s
from errors import ApiError

bp = Blueprint("insurance", __name__)

DECISIONS = {"APPROVE", "DENY"}


def _mastectomy_lines(order_id):
    result = []
    for line in store.order_lines.values():
        if line["order_id"] != order_id:
            continue
        if line["status"] == "CANCELLED":
            continue
        sku = store.skus.get(line["sku_id"])
        product = store.products.get(sku["product_id"]) if sku else None
        if product and product["is_mastectomy"]:
            result.append(line)
    return result


@bp.post("/boutique/insurance-claims")
def submit_claim():
    h.require_role("BillingClerk")
    body = h.get_body()
    if body.get("order_id") is not None:
        order = h.lookup("orders", body["order_id"])
    else:
        order = None
    h.require_fields(body, ["order_id"])
    # state (priority 7): order must be PAID
    if order["payment_status"] != "PAID":
        raise ApiError("ERR_ORDER_NOT_PAID")
    # referential (priority 12): at least one mastectomy line
    mast = _mastectomy_lines(order["id"])
    if not mast:
        raise ApiError("ERR_NOT_MASTECTOMY_ORDER")
    claim_amount = sum(l["line_net_cents"] for l in mast)
    rec = store.new_record({
        "order_id": order["id"],
        "claim_amount_cents": claim_amount,
        "adjudicated_amount_cents": None,
        "decision": "PENDING",
        "covered_amount_cents": calc.insurance_coverage(claim_amount),  # ESTIMATE
        "reimbursed_cents": 0,
        "status": "SUBMITTED",
    })
    store.claims[rec["id"]] = rec
    return h.success(s.claim_out(rec), status=201)


@bp.get("/boutique/insurance-claims/<cid>")
def get_claim(cid):
    h.require_role("Customer", "StoreManager", "BillingClerk")
    rec = h.lookup("claims", cid)
    if g.role == "Customer":
        order = store.orders.get(rec["order_id"])
        if order:
            h.owner_guard(order["customer_id"])
    return h.success(s.claim_out(rec))


@bp.get("/boutique/insurance-claims")
def list_claims():
    h.require_role("Customer", "StoreManager", "BillingClerk")
    order_id = h.filter_arg("order_id")

    def pred(r):
        return order_id is None or r["order_id"] == order_id

    return h.list_response("claims", s.claim_out, pred)


@bp.post("/boutique/insurance-claims/<cid>/adjudicate")
def adjudicate_claim(cid):
    h.require_role("BillingClerk")
    claim = h.lookup("claims", cid)
    body = h.get_body()
    # validation (priority 5)
    h.require_fields(body, ["decision"])
    h.check_enum(body["decision"], DECISIONS, "decision")
    adjudicated = None
    if body["decision"] == "APPROVE":
        adjudicated = body.get("adjudicated_amount_cents")
        if not isinstance(adjudicated, int) or isinstance(adjudicated, bool) or adjudicated < 0:
            raise ApiError("ERR_VALIDATION", "adjudicated_amount_cents must be an integer >= 0")
    # state (priority 7)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    if body["decision"] == "APPROVE":
        claim["adjudicated_amount_cents"] = adjudicated
        claim["decision"] = "APPROVE"
        claim["covered_amount_cents"] = calc.insurance_coverage(adjudicated)  # FINAL
        claim["status"] = "APPROVED"
    else:  # DENY
        claim["decision"] = "DENY"
        claim["covered_amount_cents"] = 0
        claim["status"] = "DENIED"
    store.touch(claim)
    return h.success(s.claim_out(claim))


@bp.post("/boutique/insurance-claims/<cid>/reimburse")
def reimburse_claim(cid):
    h.require_role("BillingClerk")
    claim = h.lookup("claims", cid)
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    if claim["covered_amount_cents"] <= 0:
        raise ApiError("ERR_NOTHING_TO_REIMBURSE")
    claim["reimbursed_cents"] = claim["covered_amount_cents"]
    claim["status"] = "REIMBURSED"
    store.touch(claim)
    order = store.orders.get(claim["order_id"])
    if order:
        customer = store.customers.get(order["customer_id"])
        if customer:
            customer["store_credit_cents"] += claim["reimbursed_cents"]
            store.touch(customer)
    return h.success(s.claim_out(claim))


@bp.post("/boutique/insurance-claims/<cid>/resubmit")
def resubmit_claim(cid):
    h.require_role("BillingClerk")
    claim = h.lookup("claims", cid)
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE")
    claim["decision"] = "PENDING"
    claim["status"] = "SUBMITTED"
    claim["covered_amount_cents"] = calc.insurance_coverage(claim["claim_amount_cents"])  # ESTIMATE
    store.touch(claim)
    return h.success(s.claim_out(claim))
