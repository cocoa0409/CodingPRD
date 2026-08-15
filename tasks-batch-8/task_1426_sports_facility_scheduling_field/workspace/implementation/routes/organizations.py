"""Organization routes: register, read, reinstate (PRD 3.1)."""

from flask import Blueprint

import errors
import util
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object
from services import core

bp = Blueprint("organizations", __name__)

CLASSIFICATIONS = ("RESIDENT", "NONRESIDENT", "COMMERCIAL")
ORG_TYPES = ("YOUTH_LEAGUE", "ADULT_LEAGUE", "SCHOOL", "TOURNAMENT_OPERATOR", "CORPORATE")


@bp.post("/organizations")
def create_organization():
    require_roles("AthleticsAdmin")
    body = util.get_json_body()
    name = util.require_str(body, "name")
    classification = util.require_enum(body, "classification", CLASSIFICATIONS)
    org_type = util.require_enum(body, "org_type", ORG_TYPES)
    prior = util.optional_int(body, "prior_seasons_active", min_v=0, default=0)

    org = util.new_entity({
        "name": name,
        "classification": classification,
        "org_type": org_type,
        "prior_seasons_active": prior,
        "standing": "GOOD",
        "no_show_strikes_active": 0,
    })
    store.organizations[org["id"]] = org
    return success_object(org, 201)


@bp.get("/organizations/<oid>")
def get_organization(oid):
    require_roles(*ANY_ROLE)
    return success_object(core.get_organization(oid))


@bp.post("/organizations/<oid>/reinstate")
def reinstate_organization(oid):
    require_roles("AthleticsAdmin")
    org = core.get_organization(oid)
    if org["standing"] != "SUSPENDED":
        raise errors.ApiError(errors.ERR_ORG_SUSPENDED,
                              "Organization standing is not SUSPENDED", 409)
    org["standing"] = "PROBATION"
    util.touch(org)
    # Standing re-evaluates within the same request: the PROBATION -> GOOD
    # follow-on fires when the active count is already below 2. The upward
    # strike transitions only fire on strike-count changes, never on reinstate.
    if org["no_show_strikes_active"] < 2:
        org["standing"] = "GOOD"
        util.touch(org)
    return success_object(org)
