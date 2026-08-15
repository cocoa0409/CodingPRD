"""Participant reads."""
from flask import Blueprint

from authz import ALL_ROLES, require_roles
from db import store
from respond import success
from serialize import ser_participant
from store_ops import get_or_404

bp = Blueprint("participants", __name__)


@bp.route("/participants/<pid>", methods=["GET"])
def get_participant(pid):
    require_roles(ALL_ROLES)
    return success(ser_participant(get_or_404(store.participants, pid)))
