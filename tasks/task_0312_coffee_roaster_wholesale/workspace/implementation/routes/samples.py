"""Sample / cupping requests and conversion to orders."""
from flask import Blueprint, request

import errors
from db import store
from middleware import get_identity, require_role
from helpers import (
    get_body, require_fields, as_str, require_positive_number, as_number,
    parse_pagination, paginate, sort_by_created, new_record, touch, round_kg,
)
from response import object_response, array_response
from services import lookups, serializers
from services.orders import build_order

bp = Blueprint("samples", __name__)

MIN_CONVERT_SCORE = 80


@bp.post("/accounts/<aid>/sample-requests")
def create_sample_request(aid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "WholesaleBuyer"})
    lookups.assert_buyer_owns_account(role, user_id, aid)
    account = lookups.get_account(aid)
    body = get_body()
    require_fields(body, ["product_id", "sample_kg"])
    sample_kg = require_positive_number(body["sample_kg"], "sample_kg")
    product = lookups.get_product(as_str(body["product_id"], "product_id"))

    rec = new_record()
    rec.update({
        "account_id": account["id"],
        "product_id": product["id"],
        "sample_kg": round_kg(sample_kg),
        "cupping_score": None,
        "status": "REQUESTED",
    })
    store.sample_requests[rec["id"]] = rec
    return object_response(serializers.sample_request_public(rec), 201)


@bp.get("/accounts/<aid>/sample-requests")
def list_account_sample_requests(aid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    lookups.assert_buyer_owns_account(role, user_id, aid)
    lookups.get_account(aid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [s for s in store.sample_requests.values() if s["account_id"] == aid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.sample_request_public(s) for s in page], limit, offset, total)


@bp.get("/sample-requests")
def list_sample_requests():
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    limit, offset = parse_pagination()
    product_id = request.args.get("product_id")
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = list(store.sample_requests.values())
    if product_id is not None:
        items = [s for s in items if s["product_id"] == product_id]
    if account_id is not None:
        items = [s for s in items if s["account_id"] == account_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.sample_request_public(s) for s in page], limit, offset, total)


@bp.get("/sample-requests/<sid>")
def get_sample_request(sid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    rec = lookups.get_sample_request(sid)
    lookups.assert_buyer_owns_account(role, user_id, rec["account_id"])
    return object_response(serializers.sample_request_public(rec))


@bp.post("/sample-requests/<sid>/review")
def review_sample_request(sid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff"})
    rec = lookups.get_sample_request(sid)
    body = get_body()
    require_fields(body, ["decision", "cupping_score"])
    decision = body["decision"]
    if decision not in ("APPROVE", "DECLINE"):
        raise errors.invalid_request("decision must be APPROVE or DECLINE")
    cupping_score = as_number(body["cupping_score"], "cupping_score")
    if not (0 <= cupping_score <= 100):
        raise errors.invalid_request("cupping_score must be between 0 and 100")
    # state gate (priority 6)
    if rec["status"] != "REQUESTED":
        raise errors.invalid_state("sample request is not REQUESTED")

    rec["cupping_score"] = cupping_score
    rec["status"] = "APPROVED" if decision == "APPROVE" else "DECLINED"
    touch(rec)
    return object_response(serializers.sample_request_public(rec), 200)


@bp.post("/sample-requests/<sid>/convert")
def convert_sample_request(sid):
    _, role = get_identity()
    require_role(role, {"SalesRep"})
    rec = lookups.get_sample_request(sid)
    body = get_body()
    require_fields(body, ["qty_kg"])
    qty_kg = require_positive_number(body["qty_kg"], "qty_kg")
    # state gate (priority 6)
    if rec["status"] != "APPROVED":
        raise errors.invalid_state("sample request is not APPROVED")
    product = store.products[rec["product_id"]]
    # product mismatch: archived (priority 7)
    if product["archived"]:
        raise errors.product_mismatch("sampled product is archived")
    # minimum conversion score
    if rec["cupping_score"] is None or rec["cupping_score"] < MIN_CONVERT_SCORE:
        raise errors.invalid_state("cupping score below the minimum to convert")

    account = store.accounts[rec["account_id"]]
    order = build_order(
        account,
        [{"product_id": product["id"], "qty_kg": round_kg(qty_kg), "product": product}],
        standing_order_id=None,
    )
    rec["status"] = "CONVERTED"
    touch(rec)
    return object_response(serializers.order_public(order), 201)
