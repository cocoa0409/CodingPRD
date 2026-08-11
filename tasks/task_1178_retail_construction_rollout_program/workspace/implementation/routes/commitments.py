"""OpeningCommitment endpoints (§3.8): grand-opening date protection."""
from flask import Blueprint

from db import store
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response
from services.forecast import recompute_commitment
from util import serialize
from validate import get_or_404

bp = Blueprint("commitments", __name__)


@bp.route("/rollout/opening-commitments", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_commitments():
    return list_response(store.commitments, [
        ("site_id", "site_id", "str"),
        ("protection_posture", "protection_posture", "str"),
    ])


@bp.route("/rollout/opening-commitments/<commitmentId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_commitment(commitmentId):
    return ok(serialize(get_or_404(store.commitments, commitmentId, "opening commitment")))


@bp.route("/rollout/opening-commitments/<commitmentId>/recalculate", methods=["POST"], strict_slashes=False)
@authed(["ProgramDirector"])
def recalculate_commitment(commitmentId):
    commitment = get_or_404(store.commitments, commitmentId, "opening commitment")
    recompute_commitment(commitment)
    return ok(serialize(commitment))
