"""Guest endpoints (PRD §3.3)."""
from flask import Blueprint

import db
import response
from middleware import get_identity, require_role, get_json_body, require_owner
from services import lookup
from services.common import require_str, require_int, base_record
from services.serialize import serialize_guest

bp = Blueprint("guests", __name__)


@bp.route("/guests", methods=["POST"])
def create_guest():
    _, role = get_identity()
    require_role(role, {"BoxOffice", "Guest"})
    body = get_json_body()
    full_name = require_str(body, "full_name")
    age = require_int(body, "age", minimum=0)
    email = require_str(body, "email")

    guest = base_record()
    guest.update({
        "full_name": full_name,
        "age": age,
        "email": email,
        "wallet_credit_cents": 0,
    })
    db.guests[guest["id"]] = guest
    return response.success(serialize_guest(guest), 201)


@bp.route("/guests/<guest_id>", methods=["GET"])
def get_guest(guest_id):
    user_id, role = get_identity()
    require_role(role, {"OpsManager", "BoxOffice", "Guest"})
    guest = lookup.guest(guest_id)
    # For the guest record itself, ownership compares X-User-ID to its id.
    require_owner(role, user_id, guest["id"])
    return response.success(serialize_guest(guest), 200)
