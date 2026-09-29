"""Neighbourhood certification (PRD section 3.9)."""

from flask import Blueprint, g

import calc
import domain
from auth import auth, own
from db import db, insert
from errors import fail
from response import created, jsonable, ok, touch
from validate import body, get_enum, get_int, get_str, lookup

bp = Blueprint("communities", __name__, url_prefix="/fire-district")


def _community(community_id):
    return lookup("communities", community_id, "ERR_COMMUNITY_NOT_FOUND")


@bp.post("/communities")
def create_community():
    auth("ProgramAdmin")
    b = body()
    name = get_str(b, "name", allow_empty=False)
    organizer_name = get_str(b, "organizer_name")
    target_year = get_int(b, "target_certification_year", minimum=2020, maximum=2100)
    for existing in db.communities.values():
        if existing["name"] == name:
            fail("ERR_APN_ALREADY_REGISTERED", "Community name %r is already registered." % name)
    community = insert(db.communities, {
        "name": name,
        "organizer_name": organizer_name,
        "target_certification_year": target_year,
        "status": "ORGANIZING",
        "compliance_rate_pct": None,
        "parcels_outreached_count": 0,
        "certified_at_utc": None,
        "lapse_count": 0,
    })
    return created(jsonable(community))


@bp.get("/communities/<community_id>")
def read_community(community_id):
    auth("ProgramAdmin", "FireMarshal", "CommunityOrganizer")
    return ok(jsonable(_community(community_id)))


@bp.get("/communities/<community_id>/metrics")
def community_metrics(community_id):
    auth("ProgramAdmin", "FireMarshal", "CommunityOrganizer")
    community = _community(community_id)
    members = domain.community_parcels(community["id"])
    eligible, compliant, rate = domain.metrics_for(members)
    return ok(jsonable({
        "eligible_parcel_count": eligible,
        "compliant_parcel_count": compliant,
        "compliance_rate_pct": rate,
        "member_parcel_count": len(members),
    }))


@bp.post("/communities/<community_id>/submit-certification")
def submit_certification(community_id):
    auth("CommunityOrganizer")
    community = _community(community_id)
    own(g.user_id == community["id"])
    b = body()
    outreached = get_int(b, "parcels_outreached_count", minimum=0)
    if community["status"] != "ORGANIZING":
        fail("ERR_INVALID_STATE", "Only an ORGANIZING community may submit.")
    member_count = len(domain.community_parcels(community["id"]))
    if member_count < calc.COMMUNITY_MIN_MEMBER_PARCELS or outreached < member_count:
        fail(
            "ERR_COMMUNITY_THRESHOLD_NOT_MET",
            "The member-parcel floor or the outreach floor is not met.",
        )
    community["parcels_outreached_count"] = outreached
    community["compliance_rate_pct"] = domain.community_rate(community["id"])
    community["status"] = "SUBMITTED"
    touch(community)
    return ok(jsonable(community))


@bp.post("/communities/<community_id>/certification-decision")
def certification_decision(community_id):
    auth("FireMarshal")
    community = _community(community_id)
    b = body()
    decision = get_enum(b, "decision", ("CERTIFY", "DEFER"))
    note = get_str(b, "note", required=False)
    if community["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED community may be adjudicated.")
    if decision == "CERTIFY":
        rate = community["compliance_rate_pct"]
        if rate is None or rate < calc.COMMUNITY_CERTIFY_FLOOR_PCT:
            fail(
                "ERR_COMMUNITY_THRESHOLD_NOT_MET",
                "The community compliance rate floor is not met.",
            )
        community["status"] = "CERTIFIED"
        community["certified_at_utc"] = db.clock
    else:
        # DEFER carries no rate precondition and leaves certified_at_utc alone.
        community["status"] = "DEFERRED"
    touch(community)
    return ok(jsonable(community))


@bp.post("/communities/<community_id>/reopen-organizing")
def reopen_organizing(community_id):
    auth("CommunityOrganizer")
    community = _community(community_id)
    own(g.user_id == community["id"])
    if community["status"] not in ("DEFERRED", "LAPSED"):
        fail("ERR_INVALID_STATE", "Only a DEFERRED or LAPSED community may reopen.")
    community["status"] = "ORGANIZING"
    community["parcels_outreached_count"] = 0
    touch(community)
    return ok(jsonable(community))
