"""Source-system registry, certification and the 5-hop decertification cascade."""

from flask import Blueprint

import db
import response
import services
import validation as v
from auth import endpoint
from errors import fail

bp = Blueprint("source_systems", __name__)

STATUSES = ("REGISTERED", "CERTIFIED", "DECERTIFIED")
READERS = ("GovernanceAdmin", "DataOwner", "DataSteward", "ConsumerRep", "Auditor")


@bp.post("/mdm/source-systems")
@endpoint("GovernanceAdmin")
def create_source_system():
    body = v.body()
    code = v.req_str(body, "code", 1, 30)
    name = v.req_str(body, "name", 1)
    trust_tier = v.req_int(body, "trust_tier", 1, 5)

    for existing in db.store.source_systems.values():
        if existing["code"] == code:
            fail("ERR_DUPLICATE_SOURCE_CODE", "A source system with this code already exists.")

    source = db.create("SourceSystem", {
        "code": code,
        "name": name,
        "trust_tier": trust_tier,
        "status": "REGISTERED",
        "certified_at": None,
        "decertified_at": None,
        "decertification_reason": None,
    })
    db.store.source_systems[source["id"]] = source
    return response.created(source)


@bp.get("/mdm/source-systems")
@endpoint(*READERS)
def list_source_systems():
    limit, offset = v.pagination()
    status = v.enum_filter("status", STATUSES)
    rows = db.ordered(db.store.source_systems)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/source-systems/<source_system_id>")
@endpoint(*READERS)
def read_source_system(source_system_id):
    source = db.resolve(db.store.source_systems, source_system_id,
                        "ERR_SOURCE_SYSTEM_NOT_FOUND")
    return response.entity(source)


@bp.post("/mdm/source-systems/<source_system_id>/certify")
@endpoint("GovernanceAdmin")
def certify_source_system(source_system_id):
    source = db.resolve(db.store.source_systems, source_system_id,
                        "ERR_SOURCE_SYSTEM_NOT_FOUND")
    if source["status"] != "REGISTERED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Certification is only available from REGISTERED status.")

    source["status"] = "CERTIFIED"
    source["certified_at"] = db.now()
    db.bump(source)

    services.recompute_posture_for_source(source["id"])
    return response.entity(source)


@bp.post("/mdm/source-systems/<source_system_id>/decertify")
@endpoint("GovernanceAdmin")
def decertify_source_system(source_system_id):
    source = db.resolve(db.store.source_systems, source_system_id,
                        "ERR_SOURCE_SYSTEM_NOT_FOUND")
    body = v.body()
    reason = v.req_str(body, "reason", 1)

    if source["status"] != "CERTIFIED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Decertification is only available from CERTIFIED status.")

    # Hop 1
    source["status"] = "DECERTIFIED"
    source["decertified_at"] = db.now()
    source["decertification_reason"] = reason
    db.bump(source)

    # Hop 2
    affected = []
    for registration in db.ordered(db.store.source_registrations):
        if registration["source_system_id"] != source["id"]:
            continue
        if registration["status"] != "ACTIVE":
            continue
        registration["status"] = "REVOKED"
        registration["revoked_reason"] = "SOURCE_DECERTIFIED"
        db.bump(registration)
        if registration["domain_id"] not in affected:
            affected.append(registration["domain_id"])

    # Hops 3, 4 and 5 all fall out of the posture recompute.
    for domain_id in affected:
        domain = db.store.domains.get(domain_id)
        if domain is None:
            continue
        services.recompute_domain(domain)
        db.touch_domain(domain)

    return response.entity(source)
