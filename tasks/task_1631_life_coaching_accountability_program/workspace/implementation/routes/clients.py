"""Client registry (PRD §3.1, §3.6)."""
from flask import Blueprint, request

from auth import authenticate, require_role, body, get_str
from db import store
from envelope import success, success_list, paginate
from errors import ApiError, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE, not_found
from serializers import client as ser_client, base_row

bp = Blueprint("clients", __name__)


@bp.post("/clients")
def create_client():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager"))
    b = body()
    email = get_str(b, "email")
    if email is not None and any(c["email"] == email for c in store.clients.values()):
        raise ApiError(ERR_DUPLICATE_RESOURCE, 409, "Client email already exists")
    full_name = get_str(b, "full_name")
    tz = get_str(b, "timezone")
    if full_name is None or email is None or tz is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Required: full_name, email, timezone")
    c = base_row()
    c.update({
        "full_name": full_name,
        "email": email,
        "timezone": tz,
        "client_status": "ACTIVE",
    })
    store.clients[c["id"]] = c
    return success(ser_client(c)), 201


@bp.get("/clients/<cid>")
def get_client(cid):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    c = store.clients.get(cid)
    if c is None:
        raise not_found("Client not found")
    # score_variant=provisional substitutes the in-progress window variant;
    # anything else returns the stored final variant (PRD §3.6).
    variant = request.args.get("score_variant")
    return success(ser_client(c, variant))


@bp.get("/clients")
def list_clients():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach"))
    rows = sorted(store.clients.values(),
                  key=lambda c: (c["created_at"], c["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_client(c) for c in page], meta)
