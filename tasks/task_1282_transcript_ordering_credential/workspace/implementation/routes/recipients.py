"""Recipient endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import RECIPIENT_KINDS, get_recipient, ser_recipient, sorted_created, stamp, touch
from util import as_bool, as_enum, as_str, body, pagination_args, reject_unknown_fields, required

bp = Blueprint("recipients", __name__)

WRITE_ROLES = ["RegistrarAdmin", "RegistrarOperator"]
READ_ROLES = ["RegistrarAdmin", "RegistrarOperator", "RegistrarReviewer", "Student"]


def _routing_for_kind(kind):
    return {
        "ELECTRONIC_NETWORK": "network_code",
        "EMAIL_PDF": "email_address",
        "PAPER_MAIL": "postal_address",
        "PICKUP": None,
    }[kind]


@bp.post("/registrar/recipients")
def create_recipient():
    auth(WRITE_ROLES)
    data = body()
    reject_unknown_fields(
        data,
        {
            "kind",
            "display_name",
            "network_code",
            "email_address",
            "postal_address",
            "active",
        },
    )
    kind = as_enum(required(data, "kind"), "kind", RECIPIENT_KINDS)
    display_name = as_str(required(data, "display_name"), "display_name")
    active = data.get("active", True)
    if not isinstance(active, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "active must be a boolean")

    needed = _routing_for_kind(kind)
    fields = {}
    for f in ("network_code", "email_address", "postal_address"):
        v = data.get(f)
        if v is not None:
            v = as_str(v, f)
        fields[f] = v
    if needed is not None and not fields[needed]:
        raise ApiError(
            "ERR_RECIPIENT_ROUTING_INVALID",
            422,
            f"{needed} is required when kind == {kind}",
        )

    rec = {
        "id": new_id(),
        "kind": kind,
        "display_name": display_name,
        "network_code": fields["network_code"],
        "email_address": fields["email_address"],
        "postal_address": fields["postal_address"],
        "active": active,
    }
    stamp(rec)
    DB["recipients"][rec["id"]] = rec
    return ok(ser_recipient(rec), status=201)


@bp.get("/registrar/recipients")
def list_recipients():
    auth(READ_ROLES)
    limit, offset = pagination_args()
    items = list(DB["recipients"].values())
    kind_q = request.args.get("kind")
    if kind_q is not None:
        items = [r for r in items if r["kind"] == kind_q]
    active_q = request.args.get("active")
    if active_q is not None:
        want = active_q.lower() == "true"
        items = [r for r in items if r["active"] == want]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_recipient(r) for r in page], total, limit, offset)


@bp.get("/registrar/recipients/<rid>")
def get_one_recipient(rid):
    auth(READ_ROLES)
    return ok(ser_recipient(get_recipient(rid)))


@bp.patch("/registrar/recipients/<rid>")
def update_recipient(rid):
    auth(WRITE_ROLES)
    rec = get_recipient(rid)
    data = body()
    reject_unknown_fields(
        data,
        {"display_name", "network_code", "email_address", "postal_address", "active"},
    )
    if "display_name" in data:
        rec["display_name"] = as_str(data["display_name"], "display_name")
    for f in ("network_code", "email_address", "postal_address"):
        if f in data:
            v = data[f]
            rec[f] = None if v is None else as_str(v, f)
    if "active" in data:
        rec["active"] = as_bool(data["active"], "active")
    touch(rec)
    return ok(ser_recipient(rec))
