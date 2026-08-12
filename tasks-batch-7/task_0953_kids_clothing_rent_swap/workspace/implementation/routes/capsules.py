"""Seasonal capsule waves (PRD 3.8)."""

from flask import Blueprint

import auth
import constants as K
import derive
import envelope
import listing
import lookup
import serialize
import shape
import store
import timeutil
from errors import ApiError

bp = Blueprint("capsules", __name__)


@bp.post("/kidswear/capsules")
def create_capsule():
    auth.gate("MerchandisePlanner")
    body = shape.body_json()
    season = shape.enum_in(body, "season", K.CAPSULE_SEASONS)
    name = shape.string(body, "name")
    release_at = shape.instant(body, "release_at")
    close_at = shape.instant(body, "close_at")
    quota = shape.integer(body, "quota_per_member", required=False,
                          default=K.CAPSULE_QUOTA_PER_MEMBER_DEFAULT, minimum=0, maximum=6)
    # rung 68: same-season windows are CLOSED intervals, so adjacency collides.
    for other in store.all_rows("capsules"):
        if other["season"] != season or other["status"] == "CLOSED":
            continue
        if release_at <= other["close_at"] and other["release_at"] <= close_at:
            raise ApiError("ERR_WINDOW_OVERLAP")
    row = store.insert("capsules", {
        "season": season,
        "name": name,
        "release_at": release_at,
        "close_at": close_at,
        "embargo_until": None,
        "status": "DRAFT",
        "quota_per_member": quota,
    })
    return envelope.created(serialize.capsule(row))


@bp.get("/kidswear/capsules")
def list_capsules():
    auth.gate("MerchandisePlanner", "Member", "PlatformAdmin", "WarehouseOperator")
    rows = store.all_rows("capsules")
    rows = listing.eq(rows, "season", shape.query_member("season", K.CAPSULE_SEASONS))
    rows = listing.eq(rows, "status", shape.query_member("status", K.CAPSULE_STATUSES))
    return envelope.listing(rows, serialize.capsule)


@bp.get("/kidswear/capsules/<capsule_id>")
def read_capsule(capsule_id):
    auth.gate("MerchandisePlanner", "Member", "PlatformAdmin", "WarehouseOperator")
    return envelope.ok(serialize.capsule(lookup.capsule(capsule_id)))


@bp.post("/kidswear/capsules/<capsule_id>/announce")
def announce(capsule_id):
    auth.gate("MerchandisePlanner")
    capsule = lookup.capsule(capsule_id)
    if capsule["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if timeutil.now() >= capsule["release_at"]:
        raise ApiError("ERR_INVALID_STATE", "The release instant has already been reached.")
    capsule["embargo_until"] = timeutil.add_days(capsule["release_at"], K.CAPSULE_EMBARGO_DAYS)
    capsule["status"] = "ANNOUNCED"
    store.touch(capsule)
    return envelope.ok(serialize.capsule(capsule))


@bp.post("/kidswear/capsules/<capsule_id>/open")
def open_capsule(capsule_id):
    auth.gate("MerchandisePlanner")
    capsule = lookup.capsule(capsule_id)
    if capsule["status"] != "ANNOUNCED":
        raise ApiError("ERR_INVALID_STATE")
    clock = timeutil.now()
    if clock < capsule["release_at"] or clock >= capsule["close_at"]:
        raise ApiError("ERR_INVALID_STATE", "The capsule window does not admit opening now.")
    capsule["status"] = "OPEN"
    store.touch(capsule)
    return envelope.ok(serialize.capsule(capsule))


@bp.post("/kidswear/capsules/<capsule_id>/lift-embargo")
def lift_embargo(capsule_id):
    auth.gate("MerchandisePlanner")
    capsule = lookup.capsule(capsule_id)
    if capsule["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    if capsule["embargo_until"] is None or timeutil.now() < capsule["embargo_until"]:
        raise ApiError("ERR_CAPSULE_EMBARGO_NOT_REACHED")
    capsule["status"] = "EMBARGO_LIFTED"
    store.touch(capsule)
    return envelope.ok(serialize.capsule(capsule))


@bp.post("/kidswear/capsules/<capsule_id>/close")
def close_capsule(capsule_id):
    auth.gate("MerchandisePlanner")
    capsule = lookup.capsule(capsule_id)
    if capsule["status"] not in ("OPEN", "EMBARGO_LIFTED"):
        raise ApiError("ERR_INVALID_STATE")
    if timeutil.now() < capsule["close_at"]:
        raise ApiError("ERR_CAPSULE_CLOSE_NOT_DUE")
    capsule["status"] = "CLOSED"
    store.touch(capsule)
    for allocation in store.all_rows("capsule_allocations"):
        if allocation["capsule_id"] == capsule_id and allocation["status"] == "ACTIVE":
            allocation["status"] = "RELEASED"
            store.touch(allocation)
    return envelope.ok(serialize.capsule(capsule))


@bp.post("/kidswear/capsules/<capsule_id>/allocations")
def create_allocation(capsule_id):
    caller = auth.gate("Member")
    body = shape.body_json()
    member_id = shape.id_string(body, "member_id")
    units_allocated = shape.integer(body, "units_allocated", minimum=1)
    auth.own(caller, member_id)
    capsule = lookup.capsule(capsule_id)
    member = lookup.member(member_id)
    lookup.standing(member, block_pending=True, block_delinquent=True)
    lookup.pause_gate_r(member)
    if capsule["status"] != "OPEN":
        raise ApiError("ERR_CAPSULE_NOT_OPEN")
    clock = timeutil.now()
    if clock < capsule["release_at"] or clock >= capsule["close_at"]:
        raise ApiError("ERR_CAPSULE_WINDOW_CLOSED")
    if derive.completed_cycles(member_id) < K.CAPSULE_ELIGIBILITY_MIN_COMPLETED_CYCLES:
        raise ApiError("ERR_CAPSULE_ELIGIBILITY_NOT_MET")
    plan = lookup.plan(member["plan_id"])
    quota = min(capsule["quota_per_member"], plan["capsule_quota_per_wave"])
    used = 0
    for allocation in store.all_rows("capsule_allocations"):
        if (allocation["capsule_id"] == capsule_id
                and allocation["member_id"] == member_id
                and allocation["status"] == "ACTIVE"):
            used += allocation["units_allocated"]
    if units_allocated > quota - used:
        raise ApiError("ERR_CAPSULE_QUOTA_EXCEEDED")
    row = store.insert("capsule_allocations", {
        "capsule_id": capsule_id,
        "member_id": member_id,
        "units_allocated": units_allocated,
        "status": "ACTIVE",
    })
    return envelope.created(serialize.capsule_allocation(row))


@bp.get("/kidswear/capsule-allocations")
def list_allocations():
    caller = auth.gate("MerchandisePlanner", "Member", "PlatformAdmin", "WarehouseOperator")
    rows = store.all_rows("capsule_allocations")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "capsule_id", shape.query_str("capsule_id"))
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "status", shape.query_member("status", K.CAPSULE_ALLOCATION_STATUSES))
    return envelope.listing(rows, serialize.capsule_allocation)


@bp.get("/kidswear/capsule-allocations/<allocation_id>")
def read_allocation(allocation_id):
    caller = auth.gate("MerchandisePlanner", "Member", "PlatformAdmin", "WarehouseOperator")
    row = lookup.capsule_allocation(allocation_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.capsule_allocation(row))


@bp.post("/kidswear/capsule-allocations/<allocation_id>/release")
def release_allocation(allocation_id):
    auth.gate("MerchandisePlanner")
    row = lookup.capsule_allocation(allocation_id)
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    row["status"] = "RELEASED"
    store.touch(row)
    return envelope.ok(serialize.capsule_allocation(row))
