"""Authoritative source designation with optimistic concurrency (PRD 3.2)."""

from flask import Blueprint

import db
import response
import services
import validation as v
from auth import endpoint
from errors import fail

bp = Blueprint("source_registrations", __name__)

ROLES = ("AUTHORITATIVE", "CONTRIBUTING", "CONSUMING")
STATUSES = ("ACTIVE", "SUPERSEDED", "REVOKED")
READERS = ("GovernanceAdmin", "DataOwner", "DataSteward", "ConsumerRep", "Auditor")


@bp.post("/mdm/source-registrations")
@endpoint("GovernanceAdmin")
def create_registration():
    body = v.body()
    domain_id = v.req_str(body, "domain_id", 1)
    source_system_id = v.req_str(body, "source_system_id", 1)
    role = v.req_enum(body, "role", ROLES)
    trust_rank = v.req_int(body, "trust_rank", 1, 10)
    effective_from = v.req_dt(body, "effective_from")
    effective_to = v.opt_dt(body, "effective_to")
    expected_version = v.req_int(body, "expected_domain_version")

    domain = db.resolve(db.store.domains, domain_id, "ERR_DOMAIN_NOT_FOUND")
    source = db.resolve(db.store.source_systems, source_system_id,
                        "ERR_SOURCE_SYSTEM_NOT_FOUND")

    if expected_version != domain["version"]:
        fail("ERR_STALE_DOMAIN_VERSION",
             "expected_domain_version does not match the domain's current version.")

    if effective_to is not None and effective_to <= effective_from:
        fail("ERR_INVALID_INTERVAL", "effective_to must fall strictly after effective_from.")

    incumbent = None
    if role == "AUTHORITATIVE":
        incumbent = db.active_authoritative_registration(domain_id)

    registration = db.create("SourceRegistration", {
        "domain_id": domain["id"],
        "source_system_id": source["id"],
        "role": role,
        "trust_rank": trust_rank,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
        "superseded_at": None,
        "revoked_reason": None,
    })

    if incumbent is not None:
        incumbent["status"] = "SUPERSEDED"
        incumbent["superseded_at"] = db.now()
        incumbent["effective_to"] = effective_from
        db.bump(incumbent)

    db.store.source_registrations[registration["id"]] = registration

    services.recompute_domain(domain)
    db.touch_domain(domain)
    return response.created(registration)


@bp.get("/mdm/source-registrations")
@endpoint(*READERS)
def list_registrations():
    limit, offset = v.pagination()
    domain_id = v.str_filter("domain_id")
    source_system_id = v.str_filter("source_system_id")
    role = v.enum_filter("role", ROLES)
    status = v.enum_filter("status", STATUSES)

    rows = db.ordered(db.store.source_registrations)
    if domain_id is not None:
        rows = [r for r in rows if r["domain_id"] == domain_id]
    if source_system_id is not None:
        rows = [r for r in rows if r["source_system_id"] == source_system_id]
    if role is not None:
        rows = [r for r in rows if r["role"] == role]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/source-registrations/<registration_id>")
@endpoint(*READERS)
def read_registration(registration_id):
    registration = db.resolve(db.store.source_registrations, registration_id,
                              "ERR_REGISTRATION_NOT_FOUND")
    return response.entity(registration)
