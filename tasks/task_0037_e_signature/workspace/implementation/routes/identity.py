"""IdentityVerification endpoints."""

from flask import Blueprint, g

from db import LOCK
from middleware import require_roles
from response import success_object
from services import identity as svc
from services.serializers import serialize_identity_verification
from ._helpers import get_json_body


bp = Blueprint("identity", __name__)


@bp.route("/identity-verifications", methods=["POST"])
@require_roles("Signer", "ContractInitiator")
def post_iv():
    body = get_json_body()
    with LOCK:
        iv = svc.create_identity_verification(body, actor_user_id=g.user_id)
    return success_object(serialize_identity_verification(iv), 201)


@bp.route("/identity-verifications/<iid>", methods=["GET"])
@require_roles("Signer", "ContractInitiator", "EvidenceArchivist", "PlatformAdmin")
def get_iv(iid):
    with LOCK:
        iv = svc.get_identity_verification(iid)
    return success_object(serialize_identity_verification(iv))
