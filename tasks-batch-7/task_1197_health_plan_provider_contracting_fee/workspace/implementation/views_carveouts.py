"""Carve-out single-read endpoint."""

from flask import Blueprint

from envelope import ok
from helpers import get_carve_out
from security import ALL_ROLES, auth, require_roles

bp = Blueprint("carveouts", __name__)


@bp.get("/carve-outs/<cid>")
def get_one_carve_out(cid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    return ok(dict(get_carve_out(cid)))
