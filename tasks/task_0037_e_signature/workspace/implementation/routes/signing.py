"""SigningParty sign / decline."""

from flask import Blueprint, g, request

from db import LOCK
from middleware import require_roles
from response import success_object
from services import signing as svc
from services.serializers import serialize_signing_party
from ._helpers import get_json_body


bp = Blueprint("signing", __name__)


@bp.route("/signing-parties/<pid>/sign", methods=["POST"])
@require_roles("Signer")
def sign_route(pid):
    body = get_json_body()
    with LOCK:
        p = svc.sign_party(pid, body, actor_user_id=g.user_id, actor_role=g.role)
    return success_object(serialize_signing_party(p))


@bp.route("/signing-parties/<pid>/decline", methods=["POST"])
@require_roles("Signer")
def decline_route(pid):
    with LOCK:
        p = svc.decline_party(pid, actor_user_id=g.user_id, actor_role=g.role)
    return success_object(serialize_signing_party(p))
