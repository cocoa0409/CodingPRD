"""Ingestion, curation and publication of master records (PRD 3.6)."""

from flask import Blueprint

import db
import response
import services
import validation as v
from auth import endpoint, entitle
from errors import fail, invalid

bp = Blueprint("master_records", __name__)

CURATION_STATUSES = ("CANDIDATE", "CURATED", "MERGED_AWAY", "QUARANTINED")
PUBLICATION_STATUSES = ("UNPUBLISHED", "PUBLISHED", "RETRACTED")
READERS = ("GovernanceAdmin", "DataOwner", "DataSteward", "Auditor")


@bp.post("/mdm/master-records")
@endpoint("DataSteward", "DataOwner")
def create_record():
    body = v.body()
    domain_id = v.req_str(body, "domain_id", 1)
    source_system_id = v.req_str(body, "source_system_id", 1)
    natural_key = v.req_str(body, "natural_key", 1, 60)
    attributes = v.req_obj(body, "attributes")
    last_verified_at = v.req_dt(body, "last_verified_at")

    domain = db.resolve(db.store.domains, domain_id, "ERR_DOMAIN_NOT_FOUND")
    source = db.resolve(db.store.source_systems, source_system_id,
                        "ERR_SOURCE_SYSTEM_NOT_FOUND")

    entitle(domain)

    for existing in db.records_of(domain_id):
        if (existing["source_system_id"] == source["id"]
                and existing["natural_key"] == natural_key):
            fail("ERR_DUPLICATE_NATURAL_KEY",
                 "This natural_key already exists for the domain and source system.")

    record = db.create("MasterRecord", {
        "domain_id": domain["id"],
        "source_system_id": source["id"],
        "natural_key": natural_key,
        "attributes": dict(attributes),
        "completeness_pct": None,
        "last_verified_at": last_verified_at,
        "curation_status": "CANDIDATE",
        "publication_status": "UNPUBLISHED",
        "superseded_by_master_record_id": None,
        "survivorship_score": None,
        "published_at": None,
        "quarantine_reason": None,
    })
    services.refresh_record_derived(record)
    db.store.master_records[record["id"]] = record
    return response.created(record)


@bp.get("/mdm/master-records")
@endpoint(*READERS)
def list_records():
    limit, offset = v.pagination()
    domain_id = v.str_filter("domain_id")
    source_system_id = v.str_filter("source_system_id")
    superseded_by = v.str_filter("superseded_by_master_record_id")
    curation_status = v.enum_filter("curation_status", CURATION_STATUSES)
    publication_status = v.enum_filter("publication_status", PUBLICATION_STATUSES)

    rows = db.ordered(db.store.master_records)
    if domain_id is not None:
        rows = [r for r in rows if r["domain_id"] == domain_id]
    if source_system_id is not None:
        rows = [r for r in rows if r["source_system_id"] == source_system_id]
    if superseded_by is not None:
        rows = [r for r in rows if r["superseded_by_master_record_id"] == superseded_by]
    if curation_status is not None:
        rows = [r for r in rows if r["curation_status"] == curation_status]
    if publication_status is not None:
        rows = [r for r in rows if r["publication_status"] == publication_status]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/master-records/<record_id>")
@endpoint(*READERS)
def read_record(record_id):
    record = db.resolve(db.store.master_records, record_id, "ERR_MASTER_RECORD_NOT_FOUND")
    return response.entity(record)


@bp.post("/mdm/master-records/<record_id>/curate")
@endpoint("DataSteward", "DataOwner")
def curate_record(record_id):
    record = db.resolve(db.store.master_records, record_id, "ERR_MASTER_RECORD_NOT_FOUND")
    body = v.body()
    supplied_verified_at = v.opt_dt(body, "last_verified_at")

    domain = db.store.domains[record["domain_id"]]
    entitle(domain)

    if record["curation_status"] not in ("CANDIDATE", "QUARANTINED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Curation is only available from CANDIDATE or QUARANTINED status.")

    source = db.store.source_systems[record["source_system_id"]]
    if source["status"] != "CERTIFIED":
        fail("ERR_SOURCE_NOT_CERTIFIED",
             "The contributing source system is not CERTIFIED.")

    rehabilitating = record["curation_status"] == "QUARANTINED"
    if rehabilitating:
        if supplied_verified_at is None:
            invalid("Field 'last_verified_at' is required when rehabilitating a QUARANTINED record.")
        if supplied_verified_at <= record["last_verified_at"]:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Rehabilitation requires a last_verified_at strictly later than the stored value.")

    if supplied_verified_at is not None:
        record["last_verified_at"] = supplied_verified_at
    record["curation_status"] = "CURATED"
    if rehabilitating:
        record["quarantine_reason"] = None
    services.refresh_record_derived(record)
    db.bump(record)
    return response.entity(record)


@bp.post("/mdm/master-records/<record_id>/publish")
@endpoint("DataSteward", "DataOwner")
def publish_record(record_id):
    record = db.resolve(db.store.master_records, record_id, "ERR_MASTER_RECORD_NOT_FOUND")
    domain = db.store.domains[record["domain_id"]]
    entitle(domain)

    if record["publication_status"] == "PUBLISHED":
        fail("ERR_RECORD_ALREADY_PUBLISHED", "The record is already published.")
    if record["curation_status"] != "CURATED":
        fail("ERR_RECORD_NOT_CURATED", "The record is not CURATED.")
    if domain["status"] != "ACTIVE":
        fail("ERR_DOMAIN_NOT_ACTIVE", "The owning domain is not ACTIVE.")
    if domain["governance_posture"] != "OPEN":
        fail("ERR_DOMAIN_POSTURE_BLOCKED",
             "Publication requires the domain's governance posture to be OPEN.")
    if record["completeness_pct"] < services.PUBLISH_COMPLETENESS_FLOOR:
        fail("ERR_RECORD_INCOMPLETE", "The record's completeness_pct is below 60.00.")

    record["publication_status"] = "PUBLISHED"
    record["published_at"] = db.now()
    db.bump(record)

    services.recompute_domain(domain)
    db.touch_domain(domain)
    return response.entity(record)
