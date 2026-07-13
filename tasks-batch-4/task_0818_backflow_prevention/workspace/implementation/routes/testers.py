from flask import Blueprint, request

import store
from auth import authenticate, require_role
from util import ApiError, object_response, array_response, paginate, apply_list, serialize
import validate as v
import services as svc
import lookups as lk

bp = Blueprint("testers", __name__)


@bp.post("/testers")
def create_tester():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    body = v.json_object()

    raw_cert = body.get("certification_number")
    if isinstance(raw_cert, str) and raw_cert:
        if any(t["certification_number"] == raw_cert for t in store.testers.values()):
            raise ApiError("ERR_DUPLICATE_VALUE", 409, "certification_number already exists")

    name = v.req_nonempty_str(body, "name")
    cert = v.req_nonempty_str(body, "certification_number")
    eff = v.req_datetime(body, "cert_effective_date")
    exp = v.req_datetime(body, "cert_expiry_date")

    tester = {
        "name": name,
        "certification_number": cert,
        "cert_effective_date": eff,
        "cert_expiry_date": exp,
        "status": "ACTIVE",
    }
    svc.stamp_new(tester)
    store.testers[tester["id"]] = tester
    return object_response(serialize(tester), 201)


@bp.get("/testers")
def list_testers():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    limit, offset = paginate(request.args)
    status = request.args.get("status")
    pool = list(store.testers.values())
    if status is not None:
        pool = [t for t in pool if t["status"] == status]
    items, total = apply_list(pool, limit, offset)
    return array_response(items, limit, offset, total)


@bp.get("/testers/<tid>")
def get_tester(tid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "Tester"})
    tester = lk.get_tester(tid)
    return object_response(serialize(tester))


@bp.post("/testers/<tid>/suspend")
def suspend_tester(tid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    tester = lk.get_tester(tid)
    if tester["status"] != "ACTIVE":
        raise ApiError("ERR_TESTER_INVALID_STATE", 409, "tester is not ACTIVE")
    tester["status"] = "SUSPENDED"
    svc.touch(tester)
    return object_response(serialize(tester))


@bp.post("/testers/<tid>/reinstate")
def reinstate_tester(tid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    tester = lk.get_tester(tid)
    if tester["status"] != "SUSPENDED":
        raise ApiError("ERR_TESTER_INVALID_STATE", 409, "tester is not SUSPENDED")
    if store.current_utc() > tester["cert_expiry_date"]:
        raise ApiError("ERR_TESTER_NOT_CERTIFIED", 422, "certification has expired")
    tester["status"] = "ACTIVE"
    svc.touch(tester)
    return object_response(serialize(tester))
