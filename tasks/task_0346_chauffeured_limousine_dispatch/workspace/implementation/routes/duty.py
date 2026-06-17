"""Chauffeur duty/admin status events (PRD §3.3, §3.9)."""
from flask import Blueprint

import db
import views
from db import touch
from errors import ERR_FORBIDDEN, ERR_INVALID_STATE, err
from helpers import as_enum, require_fields
from middleware import authenticate, require_role
from response import success
from routes.common import get_body, must_exist

bp = Blueprint("duty", __name__)

DUTY_ACTIONS = {"CLOCK_IN", "CLOCK_OUT", "SUSPEND", "REINSTATE"}


@bp.route("/chauffeurs/<chauffeur_id>/duty-events", methods=["POST"])
def duty_events(chauffeur_id):
    user_id, role = authenticate()
    require_role(role, ["DispatchAdmin", "Chauffeur"])
    chauffeur = must_exist(db.chauffeurs, chauffeur_id, "Chauffeur")
    body = get_body()
    require_fields(body, ["action"])
    action = as_enum(body["action"], "action", DUTY_ACTIONS)

    # Chauffeur ownership: may only act on their own record (PRD §2.1).
    if role == "Chauffeur" and user_id != chauffeur_id:
        raise err(ERR_FORBIDDEN, "Chauffeur may only act on their own record")

    if action == "CLOCK_IN":
        # CLOCK_IN: Chauffeur (own) or Admin (PRD §3.3).
        if chauffeur["status"] != "OFF_DUTY":
            raise err(ERR_INVALID_STATE, "Chauffeur is not OFF_DUTY")
        chauffeur["status"] = "ON_DUTY"
        touch(chauffeur)
        return success(views.chauffeur(chauffeur))

    if action == "CLOCK_OUT":
        if chauffeur["status"] != "ON_DUTY":
            raise err(ERR_INVALID_STATE, "Chauffeur is not ON_DUTY")
        if chauffeur["active_assignment_id"] is not None:
            raise err(ERR_INVALID_STATE, "Chauffeur has an active assignment")
        chauffeur["status"] = "OFF_DUTY"
        touch(chauffeur)
        return success(views.chauffeur(chauffeur))

    if action == "SUSPEND":
        # SUSPEND reserved for DispatchAdmin (PRD §3.9).
        if role != "DispatchAdmin":
            raise err(ERR_FORBIDDEN, "Suspend is reserved for DispatchAdmin")
        if chauffeur["status"] != "OFF_DUTY":
            raise err(ERR_INVALID_STATE, "Chauffeur is not OFF_DUTY")
        chauffeur["status"] = "SUSPENDED"
        touch(chauffeur)
        return success(views.chauffeur(chauffeur))

    # REINSTATE reserved for DispatchAdmin (PRD §3.9).
    if role != "DispatchAdmin":
        raise err(ERR_FORBIDDEN, "Reinstate is reserved for DispatchAdmin")
    if chauffeur["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Chauffeur is not SUSPENDED")
    chauffeur["status"] = "OFF_DUTY"
    touch(chauffeur)
    return success(views.chauffeur(chauffeur))
