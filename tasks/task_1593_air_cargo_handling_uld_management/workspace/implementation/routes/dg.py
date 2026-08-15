"""DG declaration acceptance / rejection (PRD 3.3): the check is bound by
segregation of duties — the acting X-User-ID must differ from the booking's
created_by_user_id."""

from flask import Blueprint

import db
import serializers
from envelope import success_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_SOD_VIOLATION,
    ERR_DG_NOT_PENDING,
)
from middleware import require_roles
from util import get_json_body, require_string

bp = Blueprint("dg_declarations", __name__)


def _get_declaration(declaration_id: str) -> dict:
    declaration = db.dg_declarations.get(declaration_id)
    if declaration is None:
        raise_err(ERR_NOT_FOUND, f"DGDeclaration {declaration_id} not found")
    return declaration


def _check_preconditions(declaration: dict, user_id: str) -> None:
    # rung 5 (segregation of duties) precedes rung 6 (PENDING_CHECK state).
    booking = db.bookings[declaration["booking_id"]]
    if user_id == booking["created_by_user_id"]:
        raise_err(
            ERR_SOD_VIOLATION,
            "The DG check must be performed by someone other than the booking's creator",
        )
    if declaration["status"] != "PENDING_CHECK":
        raise_err(ERR_DG_NOT_PENDING, "Declaration must be PENDING_CHECK")


@bp.route("/dg-declarations/<declaration_id>/accept", methods=["POST"])
@require_roles("DGInspector")
def accept_declaration(declaration_id: str, _user_id: str, _role: str):
    declaration = _get_declaration(declaration_id)
    _check_preconditions(declaration, _user_id)
    declaration["status"] = "ACCEPTED"
    declaration["checked_by_user_id"] = _user_id
    db.touch(declaration)
    return success_object(serializers.dg_declaration(declaration))


@bp.route("/dg-declarations/<declaration_id>/reject", methods=["POST"])
@require_roles("DGInspector")
def reject_declaration(declaration_id: str, _user_id: str, _role: str):
    declaration = _get_declaration(declaration_id)
    body = get_json_body()
    rejection_reason = require_string(body, "rejection_reason")
    _check_preconditions(declaration, _user_id)
    declaration["status"] = "REJECTED"
    declaration["checked_by_user_id"] = _user_id
    declaration["rejection_reason"] = rejection_reason
    db.touch(declaration)
    return success_object(serializers.dg_declaration(declaration))
