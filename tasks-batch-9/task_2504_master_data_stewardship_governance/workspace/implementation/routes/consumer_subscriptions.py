"""Downstream consumers, lineage and acknowledgement (PRD 3.9)."""

from flask import Blueprint, g

import db
import response
import services
import validation as v
from auth import endpoint, entitle
from errors import fail

bp = Blueprint("consumer_subscriptions", __name__)

CLEARANCES = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
CRITICALITIES = ("TIER1", "TIER2", "TIER3")
STATUSES = ("ACTIVE", "SUSPENDED")
LINEAGE_STATUSES = ("UNDOCUMENTED", "DOCUMENTED", "STALE")
READERS = ("GovernanceAdmin", "DataOwner", "DataSteward", "ConsumerRep", "Auditor")

MIN_LINEAGE_NODES = 3


@bp.post("/mdm/consumer-subscriptions")
@endpoint("GovernanceAdmin")
def create_subscription():
    body = v.body()
    domain_id = v.req_str(body, "domain_id", 1)
    consumer_code = v.req_str(body, "consumer_code", 1, 40)
    reporting_asset_key = v.req_str(body, "reporting_asset_key", 1)
    clearance_level = v.req_enum(body, "clearance_level", CLEARANCES)
    criticality = v.req_enum(body, "criticality", CRITICALITIES)
    required_lead_days = v.req_int(body, "required_lead_days", 1, 30)

    domain = db.resolve(db.store.domains, domain_id, "ERR_DOMAIN_NOT_FOUND")

    if services.rank(clearance_level) < services.rank(domain["classification_level"]):
        fail("ERR_CLEARANCE_INSUFFICIENT",
             "The consumer's clearance_level ranks below the domain's "
             "classification_level.")

    for existing in db.store.consumer_subscriptions.values():
        if existing["consumer_code"] == consumer_code:
            fail("ERR_DUPLICATE_CONSUMER_CODE",
                 "This consumer_code is already registered.")

    subscription = db.create("ConsumerSubscription", {
        "domain_id": domain["id"],
        "consumer_code": consumer_code,
        "reporting_asset_key": reporting_asset_key,
        "clearance_level": clearance_level,
        "criticality": criticality,
        "required_lead_days": required_lead_days,
        "status": "ACTIVE",
        "lineage_path": [],
        "lineage_status": "UNDOCUMENTED",
        "lineage_revision": None,
        "lineage_documented_at": None,
        "pending_change_request_id": None,
        "notified_at": None,
        "acknowledged_at": None,
        "acknowledged_revision": None,
        "suspended_reason": None,
    })
    db.store.consumer_subscriptions[subscription["id"]] = subscription
    return response.created(subscription)


@bp.get("/mdm/consumer-subscriptions")
@endpoint(*READERS)
def list_subscriptions():
    limit, offset = v.pagination()
    domain_id = v.str_filter("domain_id")
    pending_change_request_id = v.str_filter("pending_change_request_id")
    status = v.enum_filter("status", STATUSES)
    lineage_status = v.enum_filter("lineage_status", LINEAGE_STATUSES)
    criticality = v.enum_filter("criticality", CRITICALITIES)

    rows = db.ordered(db.store.consumer_subscriptions)
    if domain_id is not None:
        rows = [r for r in rows if r["domain_id"] == domain_id]
    if pending_change_request_id is not None:
        rows = [r for r in rows
                if r["pending_change_request_id"] == pending_change_request_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if lineage_status is not None:
        rows = [r for r in rows if r["lineage_status"] == lineage_status]
    if criticality is not None:
        rows = [r for r in rows if r["criticality"] == criticality]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/consumer-subscriptions/<subscription_id>")
@endpoint(*READERS)
def read_subscription(subscription_id):
    subscription = db.resolve(db.store.consumer_subscriptions, subscription_id,
                              "ERR_SUBSCRIPTION_NOT_FOUND")
    return response.entity(subscription)


@bp.patch("/mdm/consumer-subscriptions/<subscription_id>/lineage")
@endpoint("DataSteward", "DataOwner")
def document_lineage(subscription_id):
    subscription = db.resolve(db.store.consumer_subscriptions, subscription_id,
                              "ERR_SUBSCRIPTION_NOT_FOUND")
    body = v.body()
    lineage_path = v.req_str_list(body, "lineage_path", MIN_LINEAGE_NODES)

    domain = db.store.domains[subscription["domain_id"]]
    entitle(domain)

    if subscription["lineage_status"] not in ("UNDOCUMENTED", "STALE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Lineage documentation is only available from UNDOCUMENTED or STALE "
             "status.")

    registration = db.active_authoritative_registration(domain["id"])
    if registration is None or domain["authoritative_source_code"] is None:
        fail("ERR_AUTHORITATIVE_SOURCE_UNDEFINED",
             "The domain holds no ACTIVE AUTHORITATIVE source registration.")

    if lineage_path[0] != domain["authoritative_source_code"]:
        fail("ERR_LINEAGE_SOURCE_MISMATCH",
             "The first node must equal the domain's authoritative_source_code.")
    if lineage_path[-1] != subscription["reporting_asset_key"]:
        fail("ERR_LINEAGE_TARGET_MISMATCH",
             "The last node must equal the subscription's reporting_asset_key.")
    if len(set(lineage_path)) != len(lineage_path):
        fail("ERR_LINEAGE_CYCLE", "A documented lineage path must be acyclic.")

    subscription["lineage_path"] = lineage_path
    subscription["lineage_status"] = "DOCUMENTED"
    subscription["lineage_documented_at"] = db.now()
    subscription["lineage_revision"] = domain["reference_data_revision"]
    db.bump(subscription)
    return response.entity(subscription)


@bp.post("/mdm/consumer-subscriptions/<subscription_id>/acknowledge")
@endpoint("ConsumerRep")
def acknowledge(subscription_id):
    subscription = db.resolve(db.store.consumer_subscriptions, subscription_id,
                              "ERR_SUBSCRIPTION_NOT_FOUND")

    if g.user_id != subscription["id"]:
        fail("ERR_NOT_SUBSCRIPTION_OWNER",
             "A consumer representative may act only on its own subscription.")

    if subscription["pending_change_request_id"] is None:
        fail("ERR_NO_PENDING_NOTIFICATION",
             "The subscription has no pending change notification to acknowledge.")

    domain = db.store.domains[subscription["domain_id"]]
    subscription["acknowledged_at"] = db.now()
    subscription["acknowledged_revision"] = domain["reference_data_revision"]
    db.bump(subscription)
    return response.entity(subscription)
