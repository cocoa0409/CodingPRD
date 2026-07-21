from flask import Blueprint, request

import core
from core import (
    db, ok, get_body, req_str, req_int, req_datetime, fetch,
    authenticate, authorize, require_owner, new_common, touch, serialize,
    sorted_by_created, paginate, parse_iso, credit_wallet, ApiError,
)

bp = Blueprint("permits", __name__)


@bp.route("/coop/permit-allocations", methods=["POST"])
def create_permit_allocation():
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    data = get_body()
    park_name = req_str(data, "park_name")
    season_start = req_datetime(data, "season_start")
    season_end = req_datetime(data, "season_end")
    total_quota = req_int(data, "total_quota", min_value=0)
    price_cents = req_int(data, "price_cents", min_value=0)

    alloc = new_common()
    alloc.update({
        "park_name": park_name,
        "season_start": season_start,
        "season_end": season_end,
        "total_quota": total_quota,
        "price_cents": price_cents,
        "issued_count": 0,
        "available_quota": total_quota,
    })
    db.permit_allocations[alloc["id"]] = alloc
    return ok(serialize(alloc), status=201)


@bp.route("/coop/permit-allocations/<aid>", methods=["GET"])
def get_permit_allocation(aid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    alloc = fetch("permit_allocations", aid)
    return ok(serialize(alloc))


@bp.route("/coop/permit-passes", methods=["POST"])
def issue_permit_pass():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    data = get_body()
    member_id = req_str(data, "member_id")
    permit_allocation_id = req_str(data, "permit_allocation_id")
    entry_date = req_datetime(data, "entry_date")
    expected_version = req_int(data, "expected_allocation_version")

    require_owner(role, uid, member_id)

    member = fetch("members", member_id)
    alloc = fetch("permit_allocations", permit_allocation_id)

    # business_safety (priority 5)
    if member["membership_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_INACTIVE", "Member is LAPSED; cannot buy a permit")

    # business_temporal (priority 6): entry_date within [season_start, season_end]
    entry_dt = parse_iso(entry_date)
    if not (parse_iso(alloc["season_start"]) <= entry_dt <= parse_iso(alloc["season_end"])):
        raise ApiError("ERR_OUTSIDE_SEASON", "entry_date is outside the allocation season")

    # business_constraint (priority 8): quota
    if alloc["available_quota"] < 1:
        raise ApiError("ERR_QUOTA_EXHAUSTED", "No permits remaining in this pool")

    # business_fiscal (priority 9)
    if member["store_credit_cents"] < alloc["price_cents"]:
        raise ApiError("ERR_INSUFFICIENT_STORE_CREDIT", "Insufficient store credit for permit")

    # OCC (priority 10): last, before side effects
    if expected_version != alloc["version"]:
        raise ApiError("ERR_STALE_VERSION", "PermitAllocation version has advanced")

    price = alloc["price_cents"]
    ppass = new_common()
    ppass.update({
        "member_id": member_id,
        "permit_allocation_id": permit_allocation_id,
        "entry_date": entry_date,
        "status": "ISSUED",
        "price_cents": price,
    })
    db.permit_passes[ppass["id"]] = ppass

    alloc["issued_count"] += 1
    alloc["available_quota"] = max(0, alloc["total_quota"] - alloc["issued_count"])
    touch(alloc)  # increments PermitAllocation.version by 1

    credit_wallet(member, -price)
    return ok(serialize(ppass), status=201)


@bp.route("/coop/permit-passes/<pid>", methods=["GET"])
def get_permit_pass(pid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    ppass = fetch("permit_passes", pid)
    require_owner(role, uid, ppass["member_id"])
    return ok(serialize(ppass))


@bp.route("/coop/permit-passes", methods=["GET"])
def list_permit_passes():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    member_id = request.args.get("member_id")
    if role == "Member":
        if member_id is not None and member_id != uid:
            raise ApiError("ERR_UNAUTHORIZED", "Members may only list their own permit passes")
        member_id = uid
    permit_allocation_id = request.args.get("permit_allocation_id")
    status = request.args.get("status")
    items = list(db.permit_passes.values())
    if member_id is not None:
        items = [p for p in items if p["member_id"] == member_id]
    if permit_allocation_id is not None:
        items = [p for p in items if p["permit_allocation_id"] == permit_allocation_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok(page, is_array=True, pagination=meta)
