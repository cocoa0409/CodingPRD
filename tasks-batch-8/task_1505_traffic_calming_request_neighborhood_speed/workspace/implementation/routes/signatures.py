"""Petition signature retraction (PRD §3.2)."""
from flask import Blueprint, g

from auth import require_roles
from errors import ApiError, ERR_FORBIDDEN
from helpers import get_signature, recompute_signature_count
from store import store, touch

bp = Blueprint("signatures", __name__)


@bp.delete("/api/petition-signatures/<sigId>")
@require_roles("Resident", "TrafficEngineer")
def retract_signature(sigId):
    sig = get_signature(sigId)
    # Resident callers retract only their own signature; TrafficEngineer retracts any.
    if g.role == "Resident" and sig["resident_id"] != g.user_id:
        raise ApiError(403, ERR_FORBIDDEN,
                       "A resident may only retract their own signature")
    req = store.requests[sig["request_id"]]
    del store.signatures[sigId]
    recompute_signature_count(req)
    # Note (PRD §3.2): a request already PETITION_MET does not revert.
    touch(req)
    return "", 204
