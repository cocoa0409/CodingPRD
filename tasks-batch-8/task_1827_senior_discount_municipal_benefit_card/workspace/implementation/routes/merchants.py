from flask import Blueprint

import services
import store
from auth import authenticate, authorize, require_merchant_self
from errors import (
    ERR_INVALID_REQUEST,
    ERR_MERCHANT_NOT_ACTIVE,
    ERR_MERCHANT_NOT_FOUND,
    ERR_OFFER_WINDOW_INVALID,
    ERR_OFFER_WINDOW_OVERLAP,
    raise_err,
)
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    new_record,
    opt_enum_query,
    req_date,
    req_enum,
    req_int,
    req_number,
    req_str,
    success_object,
)

bp = Blueprint("merchants", __name__)

OFFER_CATEGORIES = ("GROCERY", "PHARMACY", "DINING", "RETAIL", "SERVICES")
OFFER_STATUSES = ("ACTIVE", "RETIRED")


def _get_merchant(rid):
    return get_or_404(store.merchants, rid, ERR_MERCHANT_NOT_FOUND, "Merchant")


@bp.route("/merchants", methods=["POST"])
def create_merchant():
    _, role = authenticate()
    authorize(role, ["ProgramAdministrator"])
    body = body_json()
    name = req_str(body, "name")
    rate = req_number(body, "reimbursement_rate_pct")
    if not (rate > 0 and rate <= 100):
        raise_err(ERR_INVALID_REQUEST,
                  "reimbursement_rate_pct must be greater than 0 and at most 100")
    cap = req_int(body, "monthly_reimbursement_cap_cents")
    if cap < 0:
        raise_err(ERR_INVALID_REQUEST,
                  "monthly_reimbursement_cap_cents must be >= 0")
    rec = new_record()
    rec.update({
        "name": name,
        "reimbursement_rate_pct": rate,
        "monthly_reimbursement_cap_cents": cap,
        "status": "ACTIVE",
    })
    store.merchants[rec["id"]] = rec
    return success_object(services.merchant_out(rec), 201)


@bp.route("/merchants/<rid>", methods=["GET"])
def get_merchant(rid):
    uid, role = authenticate()
    authorize(role, ["MerchantOperator", "ProgramAdministrator", "FraudAnalyst"])
    rec = _get_merchant(rid)
    if role == "MerchantOperator":
        require_merchant_self(uid, rid)
    return success_object(services.merchant_out(rec))


@bp.route("/merchants/<rid>/terminate", methods=["POST"])
def terminate_merchant(rid):
    _, role = authenticate()
    authorize(role, ["ProgramAdministrator"])
    rec = _get_merchant(rid)
    if rec["status"] != "ACTIVE":
        raise_err(ERR_MERCHANT_NOT_ACTIVE, "Merchant is not ACTIVE")
    rec["status"] = "TERMINATED"
    bump(rec)
    for off in store.offers.values():
        if off["merchant_id"] == rec["id"] and off["status"] == "ACTIVE":
            off["status"] = "RETIRED"
            bump(off)
    for claim in store.claims.values():
        if claim["merchant_id"] == rec["id"] and claim["status"] == "SUBMITTED":
            claim["status"] = "DENIED"
            claim["denial_reason"] = "MERCHANT_TERMINATED"
            bump(claim)
    return success_object(services.merchant_out(rec))


@bp.route("/merchants/<rid>/offers", methods=["POST"])
def create_offer(rid):
    uid, role = authenticate()
    authorize(role, ["MerchantOperator"])
    merchant = _get_merchant(rid)
    if merchant["status"] != "ACTIVE":
        raise_err(ERR_MERCHANT_NOT_ACTIVE, "Merchant is not ACTIVE")
    require_merchant_self(uid, rid)
    body = body_json()
    category = req_enum(body, "category", OFFER_CATEGORIES)
    pct = req_number(body, "discount_pct")
    if not (pct > 0 and pct <= 100):
        raise_err(ERR_INVALID_REQUEST,
                  "discount_pct must be greater than 0 and at most 100")
    max_discount = req_int(body, "max_discount_cents")
    if max_discount <= 0:
        raise_err(ERR_INVALID_REQUEST, "max_discount_cents must be > 0")
    valid_from = req_date(body, "valid_from")
    valid_until = req_date(body, "valid_until")
    if not valid_from < valid_until:
        raise_err(ERR_OFFER_WINDOW_INVALID,
                  "valid_from must be strictly earlier than valid_until")
    for off in store.offers.values():
        if (off["merchant_id"] != merchant["id"] or off["category"] != category
                or off["status"] != "ACTIVE"):
            continue
        # half-open windows: adjacency (valid_until == valid_from) is allowed
        if valid_from < off["valid_until"] and off["valid_from"] < valid_until:
            raise_err(ERR_OFFER_WINDOW_OVERLAP,
                      "Window overlaps an existing ACTIVE offer of the same "
                      "merchant and category")
    rec = new_record()
    rec.update({
        "merchant_id": merchant["id"],
        "category": category,
        "discount_pct": pct,
        "max_discount_cents": max_discount,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "ACTIVE",
    })
    store.offers[rec["id"]] = rec
    return success_object(services.offer_out(rec), 201)


@bp.route("/merchants/<rid>/offers", methods=["GET"])
def list_offers(rid):
    uid, role = authenticate()
    authorize(role, ["MerchantOperator", "ProgramAdministrator", "Cardholder",
                     "FraudAnalyst"])
    merchant = _get_merchant(rid)
    if role == "MerchantOperator":
        require_merchant_self(uid, rid)
    status = opt_enum_query("status", OFFER_STATUSES)
    category = opt_enum_query("category", OFFER_CATEGORIES)
    items = [o for o in store.offers.values() if o["merchant_id"] == merchant["id"]]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if category is not None:
        items = [o for o in items if o["category"] == category]
    return list_response(items, services.offer_out)
