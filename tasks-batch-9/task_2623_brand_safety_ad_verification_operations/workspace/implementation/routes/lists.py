"""Inventory lists, their append-only entries, and pre-bid segments."""

from flask import Blueprint

import calc
import db
import middleware as mw
import response
import services as svc
import validators as v
from errors import fail
from middleware import ROLE_ADVERTISER, ROLE_PLATFORM_ADMIN
from routes.helpers import build_filters, filtered, respond_list

bp = Blueprint("lists", __name__)

LIST_TYPE_SET = {"INCLUSION", "EXCLUSION"}


def _entries_of(list_id):
    return db.ordered(
        [entry for entry in db.list_entries.values() if entry["list_id"] == list_id]
    )


# --------------------------------------------------------------------------- #
# inventory lists                                                             #
# --------------------------------------------------------------------------- #
@bp.post("/inventory-lists")
def create_inventory_list():
    caller = mw.require(ROLE_ADVERTISER)
    payload = mw.body()
    advertiser_id = payload.get("advertiser_id")
    mw.own_advertiser(caller, advertiser_id if isinstance(advertiser_id, str) else None)
    advertiser = svc.require_ref(db.advertisers, advertiser_id, "ERR_ADVERTISER_NOT_FOUND")
    list_type = v.req_enum(payload, "list_type", LIST_TYPE_SET)
    name = v.req_string(payload, "name", 1, 120)
    for existing in db.inventory_lists.values():
        if (
            existing["advertiser_id"] == advertiser["id"]
            and existing["list_type"] == list_type
            and existing["name"] == name
        ):
            fail("ERR_DUPLICATE_LIST_NAME")
    record = db.new_record(
        {
            "advertiser_id": advertiser["id"],
            "list_type": list_type,
            "name": name,
            "status": "DRAFT",
            "entry_count": 0,
            "published_version": None,
            "published_at": None,
            "stale_reason": None,
        }
    )
    db.inventory_lists[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/inventory-lists/<list_id>")
def read_inventory_list(list_id):
    caller = mw.require(ROLE_PLATFORM_ADMIN, ROLE_ADVERTISER)
    record = svc.find(db.inventory_lists, list_id)
    if record is not None:
        mw.own_advertiser(caller, record["advertiser_id"])
    else:
        fail("ERR_INVENTORY_LIST_NOT_FOUND")
    return response.object_response(record)


@bp.get("/inventory-lists")
def list_inventory_lists():
    caller = mw.require(ROLE_PLATFORM_ADMIN, ROLE_ADVERTISER)
    predicates = build_filters(
        {"advertiser_id": "advertiser_id", "list_type": "list_type", "status": "status"}
    )
    if caller.is_advertiser:
        predicates.append(lambda record: record["advertiser_id"] == caller.user_id)
    return respond_list(filtered(db.inventory_lists, predicates))


@bp.post("/inventory-lists/<list_id>/entries")
def append_entry(list_id):
    caller = mw.require(ROLE_ADVERTISER)
    parent = svc.find(db.inventory_lists, list_id)
    if parent is not None:
        mw.own_advertiser(caller, parent["advertiser_id"])
    else:
        fail("ERR_INVENTORY_LIST_NOT_FOUND")
    payload = mw.body()
    entry_type = v.req_enum(payload, "entry_type", calc.ENTRY_TYPE_SET)
    entry_value = v.req_string(payload, "entry_value", 1, 300)
    for existing in db.list_entries.values():
        if (
            existing["list_id"] == parent["id"]
            and existing["entry_type"] == entry_type
            and existing["entry_value"] == entry_value
        ):
            fail("ERR_DUPLICATE_LIST_ENTRY")
    record = db.new_record(
        {
            "list_id": parent["id"],
            "entry_type": entry_type,
            "entry_value": entry_value,
            "action": "ALLOW" if parent["list_type"] == "INCLUSION" else "BLOCK",
            "specificity_rank": calc.SPECIFICITY_RANK[entry_type],
        },
        with_common=False,
    )
    db.list_entries[record["id"]] = record
    parent["entry_count"] = int(parent["entry_count"]) + 1
    db.touch(parent)
    return response.object_response(record, 201)


@bp.get("/inventory-lists/<list_id>/entries")
def list_entries(list_id):
    caller = mw.require(ROLE_PLATFORM_ADMIN, ROLE_ADVERTISER)
    parent = svc.find(db.inventory_lists, list_id)
    if parent is not None:
        mw.own_advertiser(caller, parent["advertiser_id"])
    else:
        fail("ERR_INVENTORY_LIST_NOT_FOUND")
    records = _entries_of(parent["id"])
    entry_type = mw.query("entry_type")
    if entry_type is not None:
        records = [record for record in records if record["entry_type"] == entry_type]
    return respond_list(records)


@bp.post("/inventory-lists/<list_id>/publish")
def publish_inventory_list(list_id):
    caller = mw.require(ROLE_ADVERTISER)
    record = svc.find(db.inventory_lists, list_id)
    if record is not None:
        mw.own_advertiser(caller, record["advertiser_id"])
    else:
        fail("ERR_INVENTORY_LIST_NOT_FOUND")
    mw.body()
    if record["status"] not in ("DRAFT", "STALE"):
        fail("ERR_INVALID_LIST_STATE")
    if int(record["entry_count"]) == 0:
        fail("ERR_EMPTY_LIST")
    for entry in _entries_of(record["id"]):
        if entry["action"] != "ALLOW" or entry["entry_type"] != "PUBLISHER":
            continue
        publisher = db.publishers.get(entry["entry_value"])
        if publisher is not None and publisher["publisher_status"] in ("RESTRICTED", "DELISTED"):
            fail("ERR_LIST_CONTAINS_RESTRICTED_PUBLISHER")
    record["published_version"] = int(record["version"])
    record["published_at"] = db.now_iso()
    record["stale_reason"] = None
    record["status"] = "PUBLISHED"
    db.touch(record)
    return response.object_response(record)


# --------------------------------------------------------------------------- #
# pre-bid segments                                                            #
# --------------------------------------------------------------------------- #
@bp.post("/pre-bid-segments")
def create_segment():
    caller = mw.require(ROLE_ADVERTISER)
    payload = mw.body()
    campaign = svc.find(db.campaigns, payload.get("campaign_id"))
    mw.own_campaign(caller, campaign)
    if campaign is None:
        fail("ERR_CAMPAIGN_NOT_FOUND")
    inclusion_id = payload.get("inclusion_list_id")
    exclusion_id = payload.get("exclusion_list_id")
    inclusion = None
    exclusion = None
    if inclusion_id is not None:
        inclusion = svc.require_ref(
            db.inventory_lists, inclusion_id, "ERR_INVENTORY_LIST_NOT_FOUND"
        )
    if exclusion_id is not None:
        exclusion = svc.require_ref(
            db.inventory_lists, exclusion_id, "ERR_INVENTORY_LIST_NOT_FOUND"
        )
    floor_tier = v.req_enum(payload, "suitability_floor_tier", calc.TIER_SET)
    # priority 18 -- list slot and ownership match
    if inclusion is not None:
        if inclusion["list_type"] != "INCLUSION":
            fail("ERR_LIST_ADVERTISER_MISMATCH")
        if inclusion["advertiser_id"] != campaign["advertiser_id"]:
            fail("ERR_LIST_ADVERTISER_MISMATCH")
    if exclusion is not None:
        if exclusion["list_type"] != "EXCLUSION":
            fail("ERR_LIST_ADVERTISER_MISMATCH")
        if exclusion["advertiser_id"] != campaign["advertiser_id"]:
            fail("ERR_LIST_ADVERTISER_MISMATCH")
    # priority 27 -- a segment must pin at least one list
    if inclusion is None and exclusion is None:
        fail("ERR_SEGMENT_REQUIRES_LIST")
    record = db.new_record(
        {
            "campaign_id": campaign["id"],
            "inclusion_list_id": inclusion["id"] if inclusion else None,
            "exclusion_list_id": exclusion["id"] if exclusion else None,
            "suitability_floor_tier": floor_tier,
            "sync_status": "PENDING",
            "synced_inclusion_version": None,
            "synced_exclusion_version": None,
            "synced_at": None,
            "stale_reason": None,
        }
    )
    db.pre_bid_segments[record["id"]] = record
    return response.object_response(record, 201)


def _segment_owner_campaign(segment):
    if segment is None:
        return None
    return db.campaigns.get(segment["campaign_id"])


@bp.get("/pre-bid-segments/<segment_id>")
def read_segment(segment_id):
    caller = mw.require(ROLE_PLATFORM_ADMIN, ROLE_ADVERTISER)
    record = svc.find(db.pre_bid_segments, segment_id)
    mw.own_campaign(caller, _segment_owner_campaign(record))
    if record is None:
        fail("ERR_PRE_BID_SEGMENT_NOT_FOUND")
    return response.object_response(record)


@bp.get("/pre-bid-segments")
def list_segments():
    caller = mw.require(ROLE_PLATFORM_ADMIN, ROLE_ADVERTISER)
    predicates = build_filters(
        {
            "campaign_id": "campaign_id",
            "inclusion_list_id": "inclusion_list_id",
            "exclusion_list_id": "exclusion_list_id",
            "sync_status": "sync_status",
        }
    )
    if caller.is_advertiser:
        owned = set(
            campaign["id"]
            for campaign in db.campaigns.values()
            if campaign["advertiser_id"] == caller.user_id
        )
        predicates.append(lambda record: record["campaign_id"] in owned)
    return respond_list(filtered(db.pre_bid_segments, predicates))


@bp.post("/pre-bid-segments/<segment_id>/sync")
def sync_segment(segment_id):
    caller = mw.require(ROLE_ADVERTISER)
    record = svc.find(db.pre_bid_segments, segment_id)
    campaign = _segment_owner_campaign(record)
    mw.own_campaign(caller, campaign)
    if record is None:
        fail("ERR_PRE_BID_SEGMENT_NOT_FOUND")
    mw.body()
    if record["sync_status"] not in ("PENDING", "STALE"):
        fail("ERR_INVALID_SEGMENT_STATE")
    inclusion = db.inventory_lists.get(record["inclusion_list_id"]) if record[
        "inclusion_list_id"
    ] else None
    exclusion = db.inventory_lists.get(record["exclusion_list_id"]) if record[
        "exclusion_list_id"
    ] else None
    for pinned in (inclusion, exclusion):
        if pinned is not None and pinned["status"] != "PUBLISHED":
            fail("ERR_LIST_NOT_PUBLISHED")
    if campaign is not None and campaign["status"] != "ACTIVE":
        fail("ERR_CAMPAIGN_UNDER_REMEDIATION")
    record["synced_inclusion_version"] = (
        int(inclusion["published_version"]) if inclusion else None
    )
    record["synced_exclusion_version"] = (
        int(exclusion["published_version"]) if exclusion else None
    )
    record["synced_at"] = db.now_iso()
    record["stale_reason"] = None
    record["sync_status"] = "SYNCED"
    db.touch(record)
    return response.object_response(record)
