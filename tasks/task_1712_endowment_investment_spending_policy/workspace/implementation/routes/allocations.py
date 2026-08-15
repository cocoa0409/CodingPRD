from flask import Blueprint

from constants import ALL_ROLES, ASSET_CLASSES
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success, success_array
from services.domain import get_or_404, list_response, pool_gate
from util import new_id, parse_body, req_str, is_int

bp = Blueprint("allocations", __name__)


@bp.route("/endowment/allocations/bulk_upsert", methods=["POST"])
def bulk_upsert():
    authenticate(["EndowmentAdmin"])
    body = parse_body(required=True)
    pool_id = req_str(body, "pool_id")
    items = body.get("items")
    if not isinstance(items, list):
        raise_err("ERR_INVALID_REQUEST", "items must be an array")
    parsed = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise_err("ERR_INVALID_REQUEST", f"items[{i}] must be an object")
        ac = item.get("asset_class")
        if not isinstance(ac, str) or ac not in ASSET_CLASSES:
            raise_err(
                "ERR_INVALID_REQUEST",
                f"items[{i}].asset_class must be one of {', '.join(ASSET_CLASSES)}",
            )
        target = item.get("target_pct_bps")
        if not is_int(target) or not (0 <= target <= 10000):
            raise_err(
                "ERR_INVALID_REQUEST",
                f"items[{i}].target_pct_bps must be an integer in 0..10000",
            )
        band = item.get("rebalance_band_bps")
        if not is_int(band) or not (1 <= band <= 5000):
            raise_err(
                "ERR_INVALID_REQUEST",
                f"items[{i}].rebalance_band_bps must be an integer in 1..5000",
            )
        parsed.append((ac, target, band))

    pool = get_or_404(store.pools, pool_id, "EndowmentPool")
    pool_gate(pool, "allocation_bulk_upsert")

    seen = set()
    for ac, _, _ in parsed:
        if ac in seen:
            raise_err(
                "ERR_DUPLICATE_RECORD",
                f"Duplicate asset_class {ac} within items",
            )
        seen.add(ac)

    if sum(t for _, t, _ in parsed) != 10000:
        raise_err(
            "ERR_ALLOCATION_SUM_INVALID",
            "Pool allocation targets must sum to exactly 10000 bps",
        )

    existing = {
        a["asset_class"]: a
        for a in store.allocations.values()
        if a["pool_id"] == pool_id
    }
    wanted = {ac: (t, b) for ac, t, b in parsed}

    # Rows absent from items are deleted; matching rows are updated.
    for ac, alloc in list(existing.items()):
        if ac not in wanted:
            del store.allocations[alloc["id"]]
    for ac, (target, band) in wanted.items():
        if ac in existing:
            alloc = existing[ac]
            if (
                alloc["target_pct_bps"] != target
                or alloc["rebalance_band_bps"] != band
            ):
                alloc["target_pct_bps"] = target
                alloc["rebalance_band_bps"] = band
                bump(alloc)
        else:
            rec = {
                "id": new_id(),
                "pool_id": pool_id,
                "asset_class": ac,
                "target_pct_bps": target,
                "rebalance_band_bps": band,
                "actual_pct_bps": 0,
                "drift_status": "IN_BAND",
                "drift_acknowledged": False,
                "version": 1,
            }
            stamp_new(rec)
            store.allocations[rec["id"]] = rec

    rows = [
        a for a in store.allocations.values() if a["pool_id"] == pool_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return success_array([pub(r) for r in rows])


@bp.route("/endowment/allocations", methods=["GET"])
def list_allocations():
    authenticate(ALL_ROLES)
    return list_response(
        store.allocations,
        [
            ("pool_id", "pool_id", "str"),
            ("asset_class", "asset_class", "str"),
            ("drift_status", "drift_status", "str"),
        ],
    )


@bp.route("/endowment/allocations/<allocation_id>", methods=["GET"])
def get_allocation(allocation_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.allocations, allocation_id, "AssetClassAllocation")))


@bp.route("/endowment/allocations/<allocation_id>/acknowledge_drift", methods=["POST"])
def acknowledge_drift(allocation_id):
    authenticate(["BoardMember"])
    alloc = get_or_404(store.allocations, allocation_id, "AssetClassAllocation")
    if alloc["drift_status"] != "BREACHED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            "Drift may be acknowledged only while the allocation is BREACHED",
        )
    pool = store.pools.get(alloc["pool_id"])
    if pool is not None and pool["pool_status"] == "TERMINATED":
        raise_err(
            "ERR_POOL_SUSPENDED",
            "Pool is TERMINATED and read-only; all mutations are rejected",
        )
    alloc["drift_acknowledged"] = True
    bump(alloc)
    return success(pub(alloc))
