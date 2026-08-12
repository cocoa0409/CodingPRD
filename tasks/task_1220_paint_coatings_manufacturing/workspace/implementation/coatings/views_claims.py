"""Credit claim endpoints: submit, review, approve, reject, settle, void."""
from datetime import timedelta

from flask import Blueprint, request

from .domain import CLAIM_TYPES, CLAIM_WINDOW_DAYS, credit_cents, ser_credit_claim
from .errors import ApiError, invalid_state, not_found, unprocessable
from .store import now, store
from .util import auth, body, list_response, new_record, success, touch, v_enum, v_int, v_str

bp = Blueprint("credit_claims", __name__)

ALL = ("PlantManager", "LabTechnician", "ProductionOperator", "QCInspector", "RegulatoryClerk", "Dealer")


def _dealer_owns(claim, user_id, role):
    if role == "Dealer" and claim["customer_id"] != user_id:
        raise ApiError(403, "ERR_FORBIDDEN", "Dealer may only act on its own credit claims")


@bp.post("/coatings/credit-claims")
def create_claim():
    user_id, _role = auth(("Dealer",))
    b = body()
    # gate 2: entity-backed ownership
    if "customer_id" in b and b["customer_id"] is not None and b["customer_id"] != user_id:
        raise ApiError(403, "ERR_FORBIDDEN", "Dealer may only claim for its own customer record")
    customer_id = v_str(b, "customer_id")
    container_id = v_str(b, "container_id")
    claim_type = v_enum(b, "claim_type", CLAIM_TYPES)
    invoice_value_cents = v_int(b, "invoice_value_cents", minv=1)
    claimed_exposure_count = v_int(b, "claimed_exposure_count", required=False, minv=0)
    if claimed_exposure_count is None:
        claimed_exposure_count = 0
    # gate 4: existence
    if customer_id not in store.customers:
        raise not_found()
    container = store.containers.get(container_id)
    if container is None:
        raise not_found()
    # gate 8: container must be SHIPPED to the claiming customer
    creditable = False
    if container["status"] == "SHIPPED" and container.get("order_id"):
        order = store.orders.get(container["order_id"])
        if order is not None and order["customer_id"] == customer_id:
            creditable = True
    if not creditable:
        raise unprocessable("ERR_CONTAINER_NOT_CREDITABLE", "Container was not shipped to the claiming customer")
    # gate 9: 30-day claim window, second-level precision, exactly 30 days passes
    created = now()
    if created > container["shipped_at"] + timedelta(days=CLAIM_WINDOW_DAYS):
        raise unprocessable("ERR_CLAIM_WINDOW_EXPIRED", "Claim submitted more than 30 days after shipment")
    remaining_days = (container["expiry_date"] - created).days
    provisional = credit_cents(invoice_value_cents, remaining_days, claim_type, claimed_exposure_count)
    rec = new_record()
    rec.update({
        "customer_id": customer_id,
        "container_id": container_id,
        "claim_type": claim_type,
        "invoice_value_cents": invoice_value_cents,
        "claimed_exposure_count": claimed_exposure_count,
        "verified_exposure_count": None,
        "remaining_days_at_claim": remaining_days,
        "provisional_credit_cents": provisional,
        "final_credit_cents": None,
        "reviewed_by_user_id": None,
        "approved_by_user_id": None,
        "settled_by_user_id": None,
        "status": "SUBMITTED",
    })
    store.credit_claims[rec["id"]] = rec
    return success(ser_credit_claim(rec), 201)


@bp.get("/coatings/credit-claims/<cid>")
def get_claim(cid):
    user_id, role = auth(ALL)
    rec = store.credit_claims.get(cid)
    if rec is None:
        raise not_found()
    _dealer_owns(rec, user_id, role)
    return success(ser_credit_claim(rec), 200)


@bp.get("/coatings/credit-claims")
def list_claims():
    user_id, role = auth(ALL)
    recs = list(store.credit_claims.values())
    if role == "Dealer":
        recs = [c for c in recs if c["customer_id"] == user_id]
    cust = request.args.get("customer_id")
    if cust is not None:
        recs = [c for c in recs if c["customer_id"] == cust]
    cont = request.args.get("container_id")
    if cont is not None:
        recs = [c for c in recs if c["container_id"] == cont]
    return list_response(recs, ser_credit_claim)


@bp.post("/coatings/credit-claims/<cid>/review")
def review_claim(cid):
    user_id, _role = auth(("RegulatoryClerk",))
    rec = store.credit_claims.get(cid)
    if rec is None:
        raise not_found()
    if rec["status"] != "SUBMITTED":
        raise invalid_state("Claim is not SUBMITTED")
    container = store.containers.get(rec["container_id"])
    rec["verified_exposure_count"] = container["freeze_exposure_count"] if container else 0
    rec["reviewed_by_user_id"] = user_id
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return success(ser_credit_claim(rec), 200)


@bp.post("/coatings/credit-claims/<cid>/approve")
def approve_claim(cid):
    user_id, _role = auth(("PlantManager",))
    rec = store.credit_claims.get(cid)
    if rec is None:
        raise not_found()
    if rec["status"] != "UNDER_REVIEW":
        raise invalid_state("Claim is not UNDER_REVIEW")
    final = credit_cents(
        rec["invoice_value_cents"], rec["remaining_days_at_claim"], rec["claim_type"], rec["verified_exposure_count"]
    )
    customer = store.customers.get(rec["customer_id"])
    remaining_cap = customer["annual_credit_cap_cents"] - customer["credit_used_ytd_cents"]
    if final > remaining_cap:
        raise unprocessable("ERR_CREDIT_CAP_EXCEEDED", "Final credit exceeds the customer's remaining annual cap")
    rec["final_credit_cents"] = final
    rec["approved_by_user_id"] = user_id
    rec["status"] = "APPROVED"
    touch(rec)
    return success(ser_credit_claim(rec), 200)


@bp.post("/coatings/credit-claims/<cid>/reject")
def reject_claim(cid):
    auth(("PlantManager",))
    rec = store.credit_claims.get(cid)
    if rec is None:
        raise not_found()
    if rec["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise invalid_state("Claim cannot be rejected from %s" % rec["status"])
    rec["status"] = "REJECTED"
    touch(rec)
    return success(ser_credit_claim(rec), 200)


@bp.post("/coatings/credit-claims/<cid>/settle")
def settle_claim(cid):
    user_id, _role = auth(("PlantManager",))
    rec = store.credit_claims.get(cid)
    if rec is None:
        raise not_found()
    if rec["status"] != "APPROVED":
        raise invalid_state("Claim is not APPROVED")
    if user_id == rec["approved_by_user_id"]:
        raise unprocessable("ERR_SEGREGATION_OF_DUTY", "Settler must differ from the approver")
    customer = store.customers.get(rec["customer_id"])
    customer["credit_balance_cents"] += rec["final_credit_cents"]
    customer["credit_used_ytd_cents"] += rec["final_credit_cents"]
    touch(customer)
    rec["settled_by_user_id"] = user_id
    rec["status"] = "SETTLED"
    touch(rec)
    return success(ser_credit_claim(rec), 200)


@bp.post("/coatings/credit-claims/<cid>/void")
def void_claim(cid):
    auth(("PlantManager",))
    rec = store.credit_claims.get(cid)
    if rec is None:
        raise not_found()
    if rec["status"] != "SETTLED":
        raise invalid_state("Claim is not SETTLED")
    customer = store.customers.get(rec["customer_id"])
    customer["credit_balance_cents"] -= rec["final_credit_cents"]
    customer["credit_used_ytd_cents"] -= rec["final_credit_cents"]
    touch(customer)
    rec["status"] = "VOIDED"
    touch(rec)
    return success(ser_credit_claim(rec), 200)
