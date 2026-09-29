"""ToolSku catalogue endpoints (PRD §3.1)."""

from flask import Blueprint

import calculations as calc
import services as svc
from errors import ApiError
from envelope import ok, ok_list
from routes.helpers import ensure_unique_code, listing
from serialize import claim_line_out, lot_out, pack_member_out, report_out, sku_out
from store import base_row, store, touch, with_common
from validate import (auth, filter_arg, get_body, lookup, req_enum, req_int, req_str,
                     require_present, resolve_optional_ref)

skus_bp = Blueprint("skus", __name__)

READ_ROLES = ["ChannelManager", "ProductionPlanner", "QualityEngineer",
              "WarrantyAdministrator", "BrandProtectionAnalyst", "PlatformAdmin"]
WRITE_ROLES = ["ChannelManager", "PlatformAdmin"]


def _lineage(candidate_id, tool_family, self_id=None):
    """Cycle (910) then family (911) then depth (912). Returns lineage_depth."""
    if candidate_id is None:
        return 0
    try:
        hops = calc.lineage_walk(store.skus, candidate_id, self_id)
    except calc.LineageError as exc:
        raise ApiError(exc.error_id)
    ancestor = store.skus.get(candidate_id)
    if ancestor is not None and ancestor["tool_family"] != tool_family:
        raise ApiError("ERR_LINEAGE_FAMILY_MISMATCH")
    if hops > calc.LINEAGE_MAX_DEPTH:
        raise ApiError("ERR_LINEAGE_DEPTH_EXCEEDED")
    return hops


@skus_bp.post("/toolworks/tool-skus")
def create_sku():
    auth(*WRITE_ROLES)
    body = get_body()

    ancestor_present, ancestor = resolve_optional_ref(
        body, "supersedes_sku_id", store.skus, "ERR_TOOL_SKU_NOT_FOUND")

    sku_code = req_str(body, "sku_code", 1, 32)
    tool_family = req_enum(body, "tool_family", calc.TOOL_FAMILIES)
    channel = req_enum(body, "channel", calc.CHANNELS)
    nominal_size_mm = req_int(body, "nominal_size_mm", 1, 80)
    alloy_grade = req_enum(body, "alloy_grade", calc.ALLOY_GRADES)
    list_price_cents = req_int(body, "list_price_cents", 1)
    warranty_tier = req_enum(body, "warranty_tier", calc.WARRANTY_TIERS)

    candidate_id = ancestor["id"] if ancestor is not None else None
    lineage_depth = _lineage(candidate_id, tool_family)

    ensure_unique_code(store.skus, "sku_code", sku_code)

    row = with_common(base_row(
        sku_code=sku_code,
        tool_family=tool_family,
        channel=channel,
        nominal_size_mm=nominal_size_mm,
        alloy_grade=alloy_grade,
        list_price_cents=list_price_cents,
        warranty_tier=warranty_tier,
        supersedes_sku_id=candidate_id,
        lineage_depth=lineage_depth,
        proof_torque_required_nm=calc.proof_torque_requirement(
            tool_family, nominal_size_mm, alloy_grade, channel),
        brand_risk_score=0,
        warranty_posture="OPEN",
        confirmed_counterfeit_count=0,
        units_received_total=0,
        units_on_hand=0,
        units_reserved=0,
        units_shipped=0,
    ))
    store.skus[row["id"]] = row
    return ok(sku_out(row), 201)


@skus_bp.get("/toolworks/tool-skus")
def list_skus():
    auth(*READ_ROLES)
    filters = {
        "channel": filter_arg("channel"),
        "tool_family": filter_arg("tool_family"),
        "warranty_posture": filter_arg("warranty_posture"),
        "supersedes_sku_id": filter_arg("supersedes_sku_id"),
    }
    items, limit, offset, total = listing(list(store.skus.values()), sku_out, filters)
    return ok_list(items, limit, offset, total)


@skus_bp.get("/toolworks/tool-skus/<id>")
def get_sku(id):
    auth(*READ_ROLES)
    row = lookup(store.skus, id, "ERR_TOOL_SKU_NOT_FOUND")
    return ok(sku_out(row))


@skus_bp.patch("/toolworks/tool-skus/<id>")
def patch_sku(id):
    auth(*WRITE_ROLES)
    row = lookup(store.skus, id, "ERR_TOOL_SKU_NOT_FOUND")
    body = get_body()

    ancestor_present, ancestor = resolve_optional_ref(
        body, "supersedes_sku_id", store.skus, "ERR_TOOL_SKU_NOT_FOUND")

    updates = {}
    if "list_price_cents" in body:
        updates["list_price_cents"] = req_int(body, "list_price_cents", 1)
    if "warranty_tier" in body:
        updates["warranty_tier"] = req_enum(body, "warranty_tier", calc.WARRANTY_TIERS)
    if "nominal_size_mm" in body:
        updates["nominal_size_mm"] = req_int(body, "nominal_size_mm", 1, 80)
    if "alloy_grade" in body:
        updates["alloy_grade"] = req_enum(body, "alloy_grade", calc.ALLOY_GRADES)

    if ancestor_present:
        candidate_id = ancestor["id"] if ancestor is not None else None
    else:
        candidate_id = row["supersedes_sku_id"]

    lineage_depth = _lineage(candidate_id, row["tool_family"], self_id=row["id"])

    row.update(updates)
    row["supersedes_sku_id"] = candidate_id
    row["lineage_depth"] = lineage_depth
    row["proof_torque_required_nm"] = calc.proof_torque_requirement(
        row["tool_family"], row["nominal_size_mm"], row["alloy_grade"], row["channel"])
    touch(row)
    return ok(sku_out(row))


@skus_bp.post("/toolworks/tool-skus/<id>/stock-receipts")
def stock_receipt(id):
    auth(*WRITE_ROLES)
    row = lookup(store.skus, id, "ERR_TOOL_SKU_NOT_FOUND")
    body = get_body()
    units_received = req_int(body, "units_received", 1)
    if "expected_sku_version" in body and body.get("expected_sku_version") is not None:
        req_int(body, "expected_sku_version")  # accepted for symmetry, never gating

    row["units_received_total"] += units_received
    svc.recompute_units(row)
    touch(row)
    return ok(sku_out(row))


@skus_bp.get("/toolworks/tool-skus/<id>/production-lots")
def sku_lots(id):
    auth("ProductionPlanner", "QualityEngineer", "ChannelManager", "PlatformAdmin")
    lookup(store.skus, id, "ERR_TOOL_SKU_NOT_FOUND")
    rows = [l for l in store.lots.values() if l["sku_id"] == id]
    items, limit, offset, total = listing(rows, lot_out)
    return ok_list(items, limit, offset, total)


@skus_bp.get("/toolworks/tool-skus/<id>/counterfeit-reports")
def sku_reports(id):
    auth("BrandProtectionAnalyst", "ChannelManager", "WarrantyAdministrator", "PlatformAdmin")
    lookup(store.skus, id, "ERR_TOOL_SKU_NOT_FOUND")
    rows = [r for r in store.reports.values() if r["sku_id"] == id]
    items, limit, offset, total = listing(rows, report_out, {"status": filter_arg("status")})
    return ok_list(items, limit, offset, total)


@skus_bp.get("/toolworks/tool-skus/<id>/pack-memberships")
def sku_pack_memberships(id):
    auth("ChannelManager", "PlatformAdmin")
    lookup(store.skus, id, "ERR_TOOL_SKU_NOT_FOUND")
    rows = [m for m in store.pack_members.values() if m["sku_id"] == id]
    items, limit, offset, total = listing(rows, pack_member_out)
    return ok_list(items, limit, offset, total)
