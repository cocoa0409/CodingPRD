from flask import Blueprint, request

from db import store, now, next_seq, new_id, touch, Rec
from errors import (
    raise_err, ERR_LAWN_NOT_FOUND, ERR_SOIL_TEST_NOT_FOUND, ERR_LAWN_ARCHIVED,
    ERR_CUSTOMER_SUSPENDED, ERR_SOIL_TEST_NOT_SHIPPED, ERR_SOIL_TEST_NOT_RETURNED,
    ERR_INVALID_REQUEST,
)
from middleware import get_body, authenticate, check_ownership, paginate, sort_items
from response import ok, ok_list
from serializers import ser_soil_test
from util import req_str, req_num, fmt_dt3

bp = Blueprint("soil_tests", __name__)

READ_ROLES = ["Customer", "Agronomist", "PlatformAdmin"]
LAB_FIELDS = ["ph", "nitrogen_ppm", "phosphorus_ppm", "potassium_ppm", "organic_matter_pct"]


@bp.route("/api/soil-tests", methods=["POST"])
def create_soil_test():
    body = get_body()
    lawn_id = req_str(body, "lawn_id")
    uid, role = authenticate(["Customer"])
    lawn = store.lawns.get(lawn_id)
    if lawn is None:
        raise_err(ERR_LAWN_NOT_FOUND, "Lawn not found")
    check_ownership(uid, role, lawn.customer_id)
    cust = store.customers.get(lawn.customer_id)
    if cust is not None and cust.status == "SUSPENDED":
        raise_err(ERR_CUSTOMER_SUSPENDED, "Customer is SUSPENDED; creates are blocked")
    if lawn.status != "ACTIVE":
        raise_err(ERR_LAWN_ARCHIVED, "Operation requires an ACTIVE lawn")

    ts = now()
    rec = Rec(
        id=new_id(), created_at=ts, updated_at=ts, version=1, seq=next_seq(),
        lawn_id=lawn_id, status="KIT_SHIPPED", reship_count=0, rejection_reason=None,
        ph=None, nitrogen_ppm=None, phosphorus_ppm=None, potassium_ppm=None,
        organic_matter_pct=None, analyzed_at=None,
    )
    rec.raw["created_at"] = fmt_dt3(ts)
    rec.raw["updated_at"] = fmt_dt3(ts)
    store.soil_tests[rec.id] = rec
    return ok(ser_soil_test(rec), 201)


@bp.route("/api/soil-tests/<kid>", methods=["GET"])
def get_soil_test(kid):
    uid, role = authenticate(READ_ROLES)
    rec = store.soil_tests.get(kid)
    if rec is None:
        raise_err(ERR_SOIL_TEST_NOT_FOUND, "Soil test not found")
    lawn = store.lawns.get(rec.lawn_id)
    check_ownership(uid, role, lawn.customer_id if lawn else None)
    return ok(ser_soil_test(rec))


@bp.route("/api/soil-tests", methods=["GET"])
def list_soil_tests():
    uid, role = authenticate(READ_ROLES)
    items = list(store.soil_tests.values())
    if role == "Customer":
        own_lawns = {l.id for l in store.lawns.values() if l.customer_id == uid}
        items = [k for k in items if k.lawn_id in own_lawns]
    lawn_id = request.args.get("lawn_id")
    if lawn_id is not None:
        items = [k for k in items if k.lawn_id == lawn_id]
    status = request.args.get("status")
    if status is not None:
        items = [k for k in items if k.status == status]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_soil_test(k) for k in page], total, limit, offset)


@bp.route("/api/soil-tests/<kid>/return-sample", methods=["POST"])
def return_sample(kid):
    uid, role = authenticate(["Customer"])
    rec = store.soil_tests.get(kid)
    if rec is None:
        raise_err(ERR_SOIL_TEST_NOT_FOUND, "Soil test not found")
    lawn = store.lawns.get(rec.lawn_id)
    check_ownership(uid, role, lawn.customer_id if lawn else None)
    if rec.status != "KIT_SHIPPED":
        raise_err(ERR_SOIL_TEST_NOT_SHIPPED, "return-sample requires KIT_SHIPPED")
    rec.status = "SAMPLE_RETURNED"
    touch(rec)
    return ok(ser_soil_test(rec))


@bp.route("/api/soil-tests/<kid>/lab-result", methods=["POST"])
def lab_result(kid):
    body = get_body()
    outcome = body.get("outcome")
    if outcome not in ("ANALYZED", "REJECTED"):
        raise_err(ERR_INVALID_REQUEST, "Field 'outcome' must be ANALYZED or REJECTED")
    lab_values = {}
    rejection_reason = None
    if outcome == "ANALYZED":
        for f in LAB_FIELDS:
            lab_values[f] = req_num(body, f)
    else:
        rr = body.get("rejection_reason")
        if not isinstance(rr, str) or not rr.strip():
            raise_err(ERR_INVALID_REQUEST, "Field 'rejection_reason' is required for REJECTED")
        rejection_reason = rr

    authenticate(["Agronomist"])
    rec = store.soil_tests.get(kid)
    if rec is None:
        raise_err(ERR_SOIL_TEST_NOT_FOUND, "Soil test not found")
    if rec.status != "SAMPLE_RETURNED":
        raise_err(ERR_SOIL_TEST_NOT_RETURNED, "lab-result requires SAMPLE_RETURNED")

    if outcome == "ANALYZED":
        for f, v in lab_values.items():
            setattr(rec, f, v)
        rec.analyzed_at = now()
        rec.raw["analyzed_at"] = fmt_dt3(rec.analyzed_at)
        rec.status = "ANALYZED"
    else:
        rec.rejection_reason = rejection_reason
        rec.reship_count += 1
        rec.status = "KIT_SHIPPED"  # resample cycle: a fresh kit is sent
    touch(rec)
    return ok(ser_soil_test(rec))
