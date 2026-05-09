"""Test-only driving endpoints."""

from flask import Blueprint

from middleware import require_roles
from response import success
from services import test_driver as svc


bp = Blueprint("test_driver", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("RegulatoryOfficer")
def advance():
    return success(svc.advance_clock())


@bp.route("/_events/emit", methods=["POST"])
@require_roles("RegulatoryOfficer")
def emit():
    return success(svc.emit_event())
