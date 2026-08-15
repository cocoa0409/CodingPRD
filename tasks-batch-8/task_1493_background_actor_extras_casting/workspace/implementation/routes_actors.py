"""BackgroundActor endpoints."""
from flask import Blueprint, request

from db import STORE
from domain import UNION_STATUSES, _base, ser_actor, touch
from errors import ApiError, ERR_ACTOR_NOT_ELIGIBLE, ERR_ACTOR_NOT_FOUND, ERR_VALIDATION
from middleware import ALL_ROLES, auth, body, req_enum, req_str
from response import ok_list, ok_obj, paginate
from services import suspend_cascade

bp = Blueprint("actors", __name__)


def get_actor(aid):
    a = STORE.actors.get(aid)
    if a is None:
        raise ApiError(ERR_ACTOR_NOT_FOUND, 404, "Background actor not found")
    return a


@bp.post("/central-casting/actors")
def create_actor():
    auth(["AgencyAdmin"])
    data = body()
    legal_name = req_str(data, "legal_name")
    union_status = req_enum(data, "union_status", UNION_STATUSES)
    special_abilities = data.get("special_abilities")
    if special_abilities is None:
        special_abilities = []
    if not isinstance(special_abilities, list) or any(
        not isinstance(x, str) for x in special_abilities
    ):
        raise ApiError(ERR_VALIDATION, 400, "special_abilities must be a list of strings")
    sizes = data.get("sizes")
    if sizes is not None and not isinstance(sizes, dict):
        raise ApiError(ERR_VALIDATION, 400, "sizes must be an object")
    a = _base()
    a.update(
        {
            "legal_name": legal_name,
            "union_status": union_status,
            "special_abilities": special_abilities,
            "sizes": sizes,
            "status": "REGISTERED",
            "no_show_count": 0,
        }
    )
    STORE.actors[a["id"]] = a
    return ok_obj(ser_actor(a), code=201)


@bp.get("/central-casting/actors")
def list_actors():
    auth(ALL_ROLES)
    rows = sorted(STORE.actors.values(), key=lambda a: a["_seq"])
    union_status = request.args.get("union_status")
    status = request.args.get("status")
    if union_status is not None:
        rows = [a for a in rows if a["union_status"] == union_status]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_actor(a) for a in page], total, limit, offset)


@bp.get("/central-casting/actors/<aid>")
def get_actor_route(aid):
    auth(ALL_ROLES)
    return ok_obj(ser_actor(get_actor(aid)))


@bp.post("/central-casting/actors/<aid>/verify")
def verify_actor(aid):
    auth(["AgencyAdmin"])
    a = get_actor(aid)
    if a["status"] != "REGISTERED":
        raise ApiError(ERR_ACTOR_NOT_ELIGIBLE, 409, "Actor is not REGISTERED")
    a["status"] = "ELIGIBLE"
    touch(a)
    return ok_obj(ser_actor(a))


@bp.post("/central-casting/actors/<aid>/suspend")
def suspend_actor(aid):
    auth(["AgencyAdmin"])
    a = get_actor(aid)
    if a["status"] != "ELIGIBLE":
        raise ApiError(ERR_ACTOR_NOT_ELIGIBLE, 409, "Actor is not ELIGIBLE")
    a["status"] = "SUSPENDED"
    suspend_cascade(a)
    touch(a)
    return ok_obj(ser_actor(a))


@bp.post("/central-casting/actors/<aid>/reinstate")
def reinstate_actor(aid):
    auth(["AgencyAdmin"])
    a = get_actor(aid)
    if a["status"] != "SUSPENDED":
        raise ApiError(ERR_ACTOR_NOT_ELIGIBLE, 409, "Actor is not SUSPENDED")
    a["status"] = "ELIGIBLE"
    a["no_show_count"] = 0
    touch(a)
    return ok_obj(ser_actor(a))
