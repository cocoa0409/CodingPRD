"""System endpoints: logical clock and SystemUser management."""
from flask import Blueprint

from db import store, now, set_clock, new_id
from errors import err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_DUPLICATE_CODE
from middleware import authorized
from response import ok, paginate
from services import ser_user, get_or_404, USER_ROLES
from util import get_body, require_fields, check_enum, parse_datetime, fmt_dt

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
@authorized("ADMIN")
def set_current_utc(_user_id=None, _role=None):
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_datetime(body["to_iso8601"], "to_iso8601")
    set_clock(dt)
    return ok({"current_utc": fmt_dt(now())})


@bp.post("/system-users")
@authorized("ADMIN")
def create_user(_user_id=None, _role=None):
    body = get_body()
    username = body.get("username")
    if isinstance(username, str) and username.strip():
        if any(u["username"] == username for u in store.users.values()):
            raise err(ERR_DUPLICATE_CODE, "username '%s' already exists" % username)
    require_fields(body, ["username", "full_name", "role", "department"])
    role = check_enum(body["role"], USER_ROLES, "role")
    rec = {
        "id": new_id(),
        "username": body["username"],
        "full_name": body["full_name"],
        "role": role,
        "department": body["department"],
        "created_at": now(),
        "_seq": store.next_seq(),
    }
    store.users[rec["id"]] = rec
    return ok(ser_user(rec), 201)


@bp.get("/system-users")
@authorized("ADMIN", "QA_MANAGER")
def list_users(_user_id=None, _role=None):
    return paginate(list(store.users.values()), ser_user)


@bp.get("/system-users/<uid>")
@authorized("ADMIN", "QA_MANAGER")
def get_user(uid, _user_id=None, _role=None):
    rec = store.users.get(uid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "SystemUser '%s' does not exist" % uid)
    return ok(ser_user(rec))
