"""Guest endpoints."""
from flask import Blueprint, request

from db import store, new_id
import errors
from middleware import get_principal, require_role, ROLE_OPERATOR, ROLE_GUEST
from response import success, success_list
from services.common import stamp_common
from services import validate as V
from services.listing import pagination, paginate
from services.serializers import serialize_guest, serialize_reservation

bp = Blueprint("guests", __name__)


@bp.route("/guests", methods=["POST"])
def create_guest():
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    body = V.get_json_body()
    V.require_fields(body, ["email", "full_name"])
    email = V.require_str(body, "email")
    full_name = V.require_str(body, "full_name")

    gid = new_id()
    guest = {
        "id": gid,
        "email": email,
        "full_name": full_name,
    }
    stamp_common(guest)
    store.guests[gid] = guest
    return success(serialize_guest(guest), 201)


@bp.route("/guests/<gid>", methods=["GET"])
def get_guest(gid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    guest = store.guests.get(gid)
    if guest is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Guest not found")
    return success(serialize_guest(guest), 200)


@bp.route("/guests/<gid>/reservations", methods=["GET"])
def list_guest_reservations(gid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    guest = store.guests.get(gid)
    if guest is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Guest not found")
    items = [r for r in store.reservations.values() if r["guest_id"] == gid]
    status = request.args.get("reservation_status")
    if status is not None:
        items = [r for r in items if r["reservation_status"] == status]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_reservation(r) for r in page], limit, offset, total)
