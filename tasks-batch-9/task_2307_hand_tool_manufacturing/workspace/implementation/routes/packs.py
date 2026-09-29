"""PackConfiguration endpoints (PRD §3.6)."""

from flask import Blueprint

import calculations as calc
import services as svc
from errors import ApiError
from envelope import ok, ok_list
from routes.helpers import ensure_unique_code, listing
from serialize import pack_member_out, pack_out
from store import base_row, store, touch, with_common
from validate import (auth, filter_arg, get_body, lookup, req_enum, req_int, req_str,
                     require_present, resolve_ref)

packs_bp = Blueprint("packs", __name__)

CM = ["ChannelManager", "PlatformAdmin"]


@packs_bp.post("/toolworks/pack-configurations")
def create_pack():
    auth(*CM)
    body = get_body()

    primary = resolve_ref(body, "primary_sku_id", store.skus, "ERR_TOOL_SKU_NOT_FOUND")
    require_present(primary, "primary_sku_id")
    pack_code = req_str(body, "pack_code")
    pack_type = req_enum(body, "pack_type", calc.PACK_TYPES)
    ensure_unique_code(store.packs, "pack_code", pack_code)

    row = with_common(base_row(
        pack_code=pack_code,
        pack_type=pack_type,
        primary_sku_id=primary["id"],
        member_subtotal_cents=0,
        security_surcharge_cents=0,
        pack_total_cents=0,
        distinct_member_count=0,
        status="DRAFT",
    ))
    store.packs[row["id"]] = row
    return ok(pack_out(row), 201)


@packs_bp.get("/toolworks/pack-configurations")
def list_packs():
    auth(*CM)
    filters = {
        "primary_sku_id": filter_arg("primary_sku_id"),
        "pack_type": filter_arg("pack_type"),
        "status": filter_arg("status"),
    }
    items, limit, offset, total = listing(list(store.packs.values()), pack_out, filters)
    return ok_list(items, limit, offset, total)


@packs_bp.get("/toolworks/pack-configurations/<id>")
def get_pack(id):
    auth(*CM)
    row = lookup(store.packs, id, "ERR_PACK_CONFIG_NOT_FOUND")
    return ok(pack_out(row))


@packs_bp.post("/toolworks/pack-configurations/<id>/members")
def add_member(id):
    auth(*CM)
    pack = lookup(store.packs, id, "ERR_PACK_CONFIG_NOT_FOUND")
    body = get_body()

    sku = resolve_ref(body, "sku_id", store.skus, "ERR_TOOL_SKU_NOT_FOUND")
    require_present(sku, "sku_id")
    quantity = req_int(body, "quantity", 1)

    if pack["status"] != "DRAFT":
        raise ApiError("ERR_PACK_STATE_INVALID")

    members = svc.pack_members(pack["id"])
    if any(m["sku_id"] == sku["id"] for m in members):
        raise ApiError("ERR_DUPLICATE_PACK_MEMBER")

    established_channel = store.skus[pack["primary_sku_id"]]["channel"]
    if members:
        established_channel = store.skus[members[0]["sku_id"]]["channel"]
    if sku["channel"] != established_channel:
        raise ApiError("ERR_CHANNEL_MIX_FORBIDDEN")

    row = base_row(
        pack_id=pack["id"],
        sku_id=sku["id"],
        quantity=quantity,
        line_extended_cents=calc.member_line_extended_cents(
            sku["list_price_cents"], quantity, pack["pack_type"]),
    )
    store.pack_members[row["id"]] = row

    svc.recompute_pack_members(pack)
    touch(pack)
    return ok(pack_member_out(row), 201)


@packs_bp.get("/toolworks/pack-configurations/<id>/members")
def list_members(id):
    auth(*CM)
    lookup(store.packs, id, "ERR_PACK_CONFIG_NOT_FOUND")
    rows = [m for m in store.pack_members.values() if m["pack_id"] == id]
    items, limit, offset, total = listing(rows, pack_member_out)
    return ok_list(items, limit, offset, total)


@packs_bp.post("/toolworks/pack-configurations/<id>/approve")
def approve_pack(id):
    auth(*CM)
    pack = lookup(store.packs, id, "ERR_PACK_CONFIG_NOT_FOUND")
    get_body()

    if pack["status"] != "DRAFT":
        raise ApiError("ERR_PACK_STATE_INVALID")

    members = svc.pack_members(pack["id"])

    for member in members:
        sku = store.skus[member["sku_id"]]
        certified = [l for l in svc.sku_lots(sku["id"]) if l["cert_status"] == "CERTIFIED"]
        if not certified:
            raise ApiError("ERR_MEMBER_SKU_NOT_CERTIFIED")

    for member in members:
        sku = store.skus[member["sku_id"]]
        if sku["warranty_posture"] == "SUSPENDED":
            raise ApiError("ERR_MEMBER_SKU_RESTRICTED")

    count = len(members)
    if pack["pack_type"] == "RETAIL_DISPLAY":
        if not 1 <= count <= 12:
            raise ApiError("ERR_PACK_CONFIG_INVALID")
    elif pack["pack_type"] == "SECURITY":
        if not 1 <= count <= 3:
            raise ApiError("ERR_PACK_CONFIG_INVALID")
        if not any(m["sku_id"] == pack["primary_sku_id"] for m in members):
            raise ApiError("ERR_PACK_CONFIG_INVALID")
    else:  # MULTIPACK
        if count < 2 or sum(m["quantity"] for m in members) < 3:
            raise ApiError("ERR_PACK_CONFIG_INVALID")

    svc.price_pack(pack)
    pack["status"] = "APPROVED"
    touch(pack)
    return ok(pack_out(pack))


@packs_bp.post("/toolworks/pack-configurations/<id>/withdraw")
def withdraw_pack(id):
    auth("ChannelManager", "BrandProtectionAnalyst", "PlatformAdmin")
    pack = lookup(store.packs, id, "ERR_PACK_CONFIG_NOT_FOUND")
    body = get_body()
    req_str(body, "withdrawal_reason")

    if pack["status"] != "APPROVED":
        raise ApiError("ERR_PACK_STATE_INVALID")

    pack["status"] = "WITHDRAWN"
    touch(pack)
    return ok(pack_out(pack))
