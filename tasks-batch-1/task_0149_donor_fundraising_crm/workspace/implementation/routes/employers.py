"""Employer endpoints (CampaignManager creates; all roles read)."""

from flask import Blueprint

import db
import lookup
import models
import response
import util
from middleware import authenticate, require_role

bp = Blueprint("employers", __name__)

ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}


@bp.post("/employers")
def create_employer():
    _, role = authenticate()
    require_role(role, {"CampaignManager"})
    with db.LOCK:
        body = util.get_json_body()
        name = util.req_string(body, "name", min_len=1, max_len=120)
        match_ratio = util.opt_number(body, "match_ratio", default=1.0,
                                      min_excl=0, max_incl=3.0)
        min_gift_cents = util.opt_int(body, "min_gift_cents", default=2500, min_val=0)
        max_match_cents = util.opt_int(body, "max_match_cents", default=1000000, min_val=1)
        annual_match_cap_cents = util.opt_int(body, "annual_match_cap_cents",
                                              default=5000000, min_val=1)

        e = models.new_record({
            "name": name,
            "match_ratio": match_ratio,
            "min_gift_cents": min_gift_cents,
            "max_match_cents": max_match_cents,
            "annual_match_cap_cents": annual_match_cap_cents,
        }, common=True)
        db.employers[e["id"]] = e
        return response.object_response(models.serialize(e), status=201)


@bp.get("/employers/<eid>")
def get_employer(eid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        e = lookup.employer(eid)
        return response.object_response(models.serialize(e))
