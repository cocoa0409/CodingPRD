"""ReversalRequest advance: TRANSMIT (OdfiOperations) or CANCEL (owner)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch
from errors import (
    raise_err,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_FOUND,
    ERR_RESOURCE_OWNERSHIP,
    ERR_REVERSAL_NOT_ACTIONABLE,
)
from middleware import require_roles
from response import success_object
from services.domain import originator_id_of_entry
from util import get_json_body, require_enum

bp = Blueprint("reversals", __name__)

ACTIONS = {"TRANSMIT", "CANCEL"}


@bp.route("/ach/reversal-requests/<reversal_id>/advance", methods=["POST"])
@require_roles("OdfiOperations", "OriginatorOps")
def advance_reversal(reversal_id: str, _user_id: str, _role: str):
    # Existence (p4)
    reversal = db.reversal_requests.get(reversal_id)
    if reversal is None:
        raise_err(ERR_NOT_FOUND, "ReversalRequest not found")
    # Schema (p5)
    body = get_json_body()
    action = require_enum(body, "action", ACTIONS)
    # Role/action match: TRANSMIT is OdfiOperations; CANCEL is the owning
    # OriginatorOps caller.
    if action == "TRANSMIT" and _role != "OdfiOperations":
        raise_err(ERR_FORBIDDEN_ROLE, "TRANSMIT requires OdfiOperations")
    if action == "CANCEL" and _role != "OriginatorOps":
        raise_err(ERR_FORBIDDEN_ROLE, "CANCEL requires OriginatorOps")
    # Ownership (p3) for the CANCEL branch.
    if action == "CANCEL":
        entry = db.ach_entries[reversal["entry_id"]]
        if originator_id_of_entry(entry) != _user_id:
            raise_err(
                ERR_RESOURCE_OWNERSHIP,
                "Caller does not own this reversal's entry's file",
            )
    # State (p6)
    if reversal["status"] != "REQUESTED":
        raise_err(ERR_REVERSAL_NOT_ACTIONABLE, "Reversal is not in REQUESTED")

    if action == "TRANSMIT":
        # Joins the re-flow sweep: settled by the next batch settle touching
        # the entry's originator.
        reversal["status"] = "TRANSMITTED"
    else:
        reversal["status"] = "CANCELLED"
    touch(reversal)
    return success_object(reversal)
