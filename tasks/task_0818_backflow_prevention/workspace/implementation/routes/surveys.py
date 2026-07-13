from flask import Blueprint, request

import store
from auth import authenticate, require_role
from util import ApiError, object_response, array_response, paginate, apply_list, serialize
import validate as v
import services as svc
import lookups as lk

bp = Blueprint("surveys", __name__)


@bp.post("/hazard-surveys")
def create_survey():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    body = v.json_object()

    raw_scid = body.get("service_connection_id")
    conn = lk.get_connection(raw_scid) if isinstance(raw_scid, str) and raw_scid else None
    if conn is not None:
        lk.ensure_owner_conn(conn, role, user_id)

    scid = v.req_nonempty_str(body, "service_connection_id")
    if conn is None:
        conn = lk.get_connection(scid)
        lk.ensure_owner_conn(conn, role, user_id)

    p = v.req_int(body, "premise_use_score", lo=0, hi=40)
    c = v.req_int(body, "chemical_exposure_score", lo=0, hi=40)
    a = v.req_int(body, "auxiliary_supply_score", lo=0, hi=40)

    survey = {
        "service_connection_id": conn["id"],
        "premise_use_score": p,
        "chemical_exposure_score": c,
        "auxiliary_supply_score": a,
        "assessed_risk_tier": None,
        "effective_risk_tier": None,
        "status": "DRAFT",
    }
    svc.stamp_new(survey)
    store.surveys[survey["id"]] = survey
    return object_response(serialize(survey), 201)


@bp.get("/hazard-surveys")
def list_surveys():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    limit, offset = paginate(request.args)

    scid = request.args.get("service_connection_id")
    status = request.args.get("status")

    pool = list(store.surveys.values())
    if scid is not None:
        pool = [s for s in pool if s["service_connection_id"] == scid]
    if status is not None:
        pool = [s for s in pool if s["status"] == status]
    if role == "PremisesOwner":
        pool = [s for s in pool
                if lk.owns_connection(store.connections.get(s["service_connection_id"]), user_id)]

    items, total = apply_list(pool, limit, offset)
    return array_response(items, limit, offset, total)


@bp.get("/hazard-surveys/<sid>")
def get_survey(sid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "PremisesOwner"})
    survey = lk.get_survey(sid)
    if role == "PremisesOwner":
        lk.ensure_owner_conn(store.connections.get(survey["service_connection_id"]), role, user_id)
    return object_response(serialize(survey))


@bp.post("/hazard-surveys/<sid>/finalize")
def finalize_survey(sid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    survey = lk.get_survey(sid)
    if survey["status"] != "DRAFT":
        raise ApiError("ERR_SURVEY_NOT_DRAFT", 409, "survey is not DRAFT")

    body = v.json_object()
    expected = v.req_int(body, "expected_service_connection_version")

    conn = store.connections[survey["service_connection_id"]]
    if expected != conn["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale service connection version")

    assessed, effective = svc.compute_risk_tiers(conn, survey)

    before = svc.begin(conn)
    survey["assessed_risk_tier"] = assessed
    survey["effective_risk_tier"] = effective
    survey["status"] = "FINALIZED"
    svc.touch(survey)
    conn["risk_tier"] = effective
    for other in store.surveys.values():
        if (other["id"] != survey["id"]
                and other["service_connection_id"] == conn["id"]
                and other["status"] == "FINALIZED"):
            other["status"] = "SUPERSEDED"
            svc.touch(other)
    svc.finish(conn, before, extra_increments=1)

    return object_response(serialize(survey))
