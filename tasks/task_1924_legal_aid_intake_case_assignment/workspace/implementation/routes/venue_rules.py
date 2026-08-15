"""VenueRule reference data (PRD section 3.9)."""
from flask import Blueprint, request

from db import db, new_id
from errors import ERR_VENUE_RULE_CONFLICT, fail
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.common import get_or_404, list_response, stamp_new_aux
from services.enums import CASE_TYPES, VENUES
from services.serialize import venue_rule_json
from validators import (body, check_allowed, req_bool, req_enum, req_int,
                        req_str)

bp = Blueprint("venue_rules", __name__)


@bp.route("/venue-rules", methods=["POST"])
@require_roles(["ProgramDirector"])
def create_venue_rule():
    b = body()
    check_allowed(b, ["county", "case_type", "venue", "priority_base_weight",
                      "extended_eligible"])
    county = req_str(b, "county")
    case_type = req_enum(b, "case_type", CASE_TYPES)
    venue = req_enum(b, "venue", VENUES)
    base_weight = req_int(b, "priority_base_weight", min_v=1, max_v=100)
    extended_eligible = req_bool(b, "extended_eligible")
    # (county, case_type) uniqueness.
    for r in db.venue_rules.values():
        if r["county"] == county and r["case_type"] == case_type:
            fail(ERR_VENUE_RULE_CONFLICT,
                 "A venue rule already exists for this county and case type")
    rec = {
        "id": new_id(),
        "county": county,
        "case_type": case_type,
        "venue": venue,
        "priority_base_weight": base_weight,
        "extended_eligible": extended_eligible,
    }
    stamp_new_aux(rec)
    db.venue_rules[rec["id"]] = rec
    return ok_object(venue_rule_json(rec), 201)


@bp.route("/venue-rules/<rid>", methods=["GET"])
@require_roles(ALL_ROLES)
def get_venue_rule(rid):
    return ok_object(venue_rule_json(get_or_404(db.venue_rules, rid)))


@bp.route("/venue-rules", methods=["GET"])
@require_roles(ALL_ROLES)
def list_venue_rules():
    records = list(db.venue_rules.values())
    for param in ("county", "case_type"):
        value = request.args.get(param)
        if value is not None:
            records = [r for r in records if r[param] == value]
    return list_response(records, venue_rule_json)
