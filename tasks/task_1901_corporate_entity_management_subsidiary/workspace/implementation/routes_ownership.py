"""Routes: OwnershipRecord create/void with OCC, DAG, and aggregate-cap checks."""
from flask import Blueprint, request

import store
import services as svc
from errors import (
    ERR_INVALID_REQUEST, ERR_ENTITY_NOT_FOUND, ERR_OWNERSHIP_RECORD_NOT_FOUND,
    ERR_ENTITY_NOT_ACTIVE, ERR_OWNERSHIP_RECORD_NOT_ACTIVE, ERR_STALE_VERSION,
    ERR_SELF_OWNERSHIP, ERR_OWNERSHIP_CYCLE, ERR_OWNERSHIP_TOTAL_EXCEEDED,
    raise_err,
)
from middleware import require_roles, get_body, ALL_ROLES
from response import ok_object, paginate, sort_records

bp = Blueprint("ownership", __name__)

CS = ["CorporateSecretary"]


def _creates_cycle(parent_id, subsidiary_id, exclude_record_id=None):
    """Would adding parent->subsidiary create a cycle among ACTIVE records?
    A cycle exists iff subsidiary already reaches parent."""
    adjacency = {}
    for r in store.ownership_records.values():
        if r["status"] != "ACTIVE" or r["id"] == exclude_record_id:
            continue
        adjacency.setdefault(r["parent_entity_id"], []).append(r["subsidiary_entity_id"])
    stack = [subsidiary_id]
    seen = set()
    while stack:
        node = stack.pop()
        if node == parent_id:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, []))
    return False


def _aggregate_cap_ok(subsidiary_id, new_eff, new_bps, superseded_id=None):
    """For every date, sum of ACTIVE percentage_bps covering it must be <= 10000.

    The record being superseded leaves the ACTIVE set (its window closes at the
    new record's effective_date, and status SUPERSEDED excludes it entirely).
    """
    records = [r for r in store.ownership_records.values()
               if r["subsidiary_entity_id"] == subsidiary_id
               and r["status"] == "ACTIVE" and r["id"] != superseded_id]
    windows = [(svc.parse_date(r["effective_date"]),
                svc.parse_date(r["end_date"]) if r["end_date"] else None,
                r["percentage_bps"]) for r in records]
    windows.append((svc.parse_date(new_eff), None, new_bps))
    breakpoints = set()
    for eff, end, _ in windows:
        breakpoints.add(eff)
        if end is not None:
            breakpoints.add(end)
    for t in sorted(breakpoints):
        total = sum(bps for eff, end, bps in windows
                    if eff <= t and (end is None or t < end))
        if total > 10000:
            return False
    return True


@bp.route("/api/ownership-records", methods=["POST"])
def create_ownership_record():
    require_roles(CS)
    body = get_body()
    # Priority 3: body FK existence
    parent_id = body.get("parent_entity_id")
    if parent_id is not None and parent_id not in store.entities:
        raise_err(ERR_ENTITY_NOT_FOUND, "parent_entity_id does not exist")
    subsidiary_id = body.get("subsidiary_entity_id")
    if subsidiary_id is not None and subsidiary_id not in store.entities:
        raise_err(ERR_ENTITY_NOT_FOUND, "subsidiary_entity_id does not exist")
    supersedes_id = body.get("supersedes_record_id")
    if supersedes_id is not None and supersedes_id not in store.ownership_records:
        raise_err(ERR_OWNERSHIP_RECORD_NOT_FOUND)
    # Priority 4: schema
    if parent_id is None:
        raise_err(ERR_INVALID_REQUEST, "parent_entity_id is required")
    if subsidiary_id is None:
        raise_err(ERR_INVALID_REQUEST, "subsidiary_entity_id is required")
    bps = body.get("percentage_bps")
    if isinstance(bps, bool) or not isinstance(bps, int) or bps < 1 or bps > 10000:
        raise_err(ERR_INVALID_REQUEST, "percentage_bps must be an integer in 1..10000")
    effective_date = body.get("effective_date")
    if not svc.is_valid_date(effective_date):
        raise_err(ERR_INVALID_REQUEST, "effective_date must be an ISO date")
    expected = body.get("expected_entity_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_entity_version is required")
    parent = store.entities[parent_id]
    subsidiary = store.entities[subsidiary_id]
    # Priority 5: both entities ACTIVE; superseded record ACTIVE
    if parent["status"] != "ACTIVE" or subsidiary["status"] != "ACTIVE":
        raise_err(ERR_ENTITY_NOT_ACTIVE,
                  "Both parent and subsidiary entities must be ACTIVE")
    superseded = None
    if supersedes_id is not None:
        superseded = store.ownership_records[supersedes_id]
        if superseded["status"] != "ACTIVE":
            raise_err(ERR_OWNERSHIP_RECORD_NOT_ACTIVE,
                      "Superseded record is not ACTIVE")
    # OCC on the subsidiary entity
    if expected != subsidiary["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_entity_version does not match the subsidiary's current version")
    # Priority 8: self-ownership, then acyclicity
    if parent_id == subsidiary_id:
        raise_err(ERR_SELF_OWNERSHIP, "parent_entity_id must differ from subsidiary_entity_id")
    if _creates_cycle(parent_id, subsidiary_id, exclude_record_id=supersedes_id):
        raise_err(ERR_OWNERSHIP_CYCLE,
                  "Record would create a cycle among ACTIVE ownership records")
    # Priority 10: temporal aggregate cap
    if not _aggregate_cap_ok(subsidiary_id, effective_date, bps,
                             superseded_id=supersedes_id):
        raise_err(ERR_OWNERSHIP_TOTAL_EXCEEDED,
                  "Aggregate ownership of the subsidiary would exceed 10000 bps")
    rec = store.new_record()
    rec.update({
        "parent_entity_id": parent_id,
        "subsidiary_entity_id": subsidiary_id,
        "percentage_bps": bps,
        "effective_date": effective_date,
        "end_date": None,
        "supersedes_record_id": supersedes_id,
        "status": "ACTIVE",
    })
    store.ownership_records[rec["id"]] = rec
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        superseded["end_date"] = effective_date
        store.touch(superseded)
    store.touch(subsidiary)  # increments subsidiary LegalEntity.version by 1
    return ok_object(svc.serialize(rec), 201)


@bp.route("/api/ownership-records", methods=["GET"])
def list_ownership_records():
    require_roles(ALL_ROLES)
    records = sort_records(list(store.ownership_records.values()))
    for param, field in (("parent_entity_id", "parent_entity_id"),
                         ("subsidiary_entity_id", "subsidiary_entity_id"),
                         ("status", "status"),
                         ("supersedes_record_id", "supersedes_record_id")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return paginate([svc.serialize(r) for r in records], request.args)


@bp.route("/api/ownership-records/<recordId>", methods=["GET"])
def get_ownership_record(recordId):
    require_roles(ALL_ROLES)
    rec = store.ownership_records.get(recordId)
    if rec is None:
        raise_err(ERR_OWNERSHIP_RECORD_NOT_FOUND)
    return ok_object(svc.serialize(rec))


@bp.route("/api/ownership-records/<recordId>/void", methods=["POST"])
def void_ownership_record(recordId):
    require_roles(CS)
    rec = store.ownership_records.get(recordId)
    if rec is None:
        raise_err(ERR_OWNERSHIP_RECORD_NOT_FOUND)
    get_body()  # optional reason
    if rec["status"] != "ACTIVE":
        raise_err(ERR_OWNERSHIP_RECORD_NOT_ACTIVE, "void requires status == ACTIVE")
    rec["status"] = "VOIDED"
    store.touch(rec)
    return ok_object(svc.serialize(rec))
