"""BillOfMaterials + BomEntry endpoints."""

from flask import Blueprint, request

from db import store, touch
from errors import (
    err, ERR_PRODUCT_NOT_FOUND, ERR_BOM_NOT_FOUND, ERR_BOM_ENTRY_NOT_FOUND,
    ERR_BOM_NOT_ARCHIVABLE, ERR_BOM_NOT_FINALIZED,
)
from middleware import require_roles, get_auth
from response import success_obj, success_list, parse_pagination
from services import engine
from services.engine import sha256_hex
from services.policy import effective_classification

bp = Blueprint("boms", __name__)


def bom_view(b):
    return {k: v for k, v in b.items() if not k.startswith("_")}


def entry_view(e):
    d = {k: v for k, v in e.items() if not k.startswith("_")}
    comp = store.components.get(e["component_id"])
    d["effective_classification"] = effective_classification(comp) if comp else None
    return d


def _resolve(productId, bomId=None, entryId=None):
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    bom = None
    entry = None
    if bomId is not None:
        bom = store.boms.get(bomId)
        if not bom or bom["product_id"] != productId:
            raise err(ERR_BOM_NOT_FOUND, "BillOfMaterials not found")
    if entryId is not None:
        entry = store.bom_entries.get(entryId)
        if not entry or entry["bom_id"] != bomId:
            raise err(ERR_BOM_ENTRY_NOT_FOUND, "BomEntry not found")
    return p, bom, entry


@bp.route("/oss-products/<productId>/boms", methods=["GET"])
def list_boms(productId):
    get_auth()
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    limit, offset = parse_pagination(request.args)
    items = [b for b in store.boms.values() if b["product_id"] == productId]
    status = request.args.get("status")
    if status:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([bom_view(b) for b in page], limit, offset, total)


@bp.route("/oss-products/<productId>/boms/<bomId>", methods=["GET"])
def get_bom(productId, bomId):
    get_auth()
    _, bom, _ = _resolve(productId, bomId)
    return success_obj(bom_view(bom))


@bp.route("/oss-products/<productId>/boms/<bomId>/entries", methods=["GET"])
def list_entries(productId, bomId):
    get_auth()
    _, bom, _ = _resolve(productId, bomId)
    limit, offset = parse_pagination(request.args)
    items = [e for e in store.bom_entries.values() if e["bom_id"] == bomId]
    eff = request.args.get("effective_classification")
    if eff:
        items = [e for e in items
                 if (effective_classification(store.components.get(e["component_id"])) if store.components.get(e["component_id"]) else None) == eff]
    det = request.args.get("obligation_determination")
    if det:
        items = [e for e in items if e.get("obligation_determination") == det]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([entry_view(e) for e in page], limit, offset, total)


@bp.route("/oss-products/<productId>/boms/<bomId>/entries/<entryId>", methods=["GET"])
def get_entry(productId, bomId, entryId):
    get_auth()
    _, _, entry = _resolve(productId, bomId, entryId)
    return success_obj(entry_view(entry))


@bp.route("/oss-products/<productId>/boms/<bomId>/generate-notice", methods=["POST"])
def generate_notice(productId, bomId):
    require_roles("ComplianceAnalyst")
    _, bom, _ = _resolve(productId, bomId)
    if bom["status"] != "FINALIZED":
        raise err(ERR_BOM_NOT_FINALIZED, "Operation requires BOM in FINALIZED status")
    bom["notice_file_generated"] = True
    content = "NOTICE\n" + bom["id"] + "\n" + ",".join(
        sorted(e["component_id"] for e in engine.entries_of_bom(bomId))
    )
    bom["notice_file_hash"] = sha256_hex(content)
    touch(bom)
    # Fulfill every NOTICE_FILE obligation ticket on this BOM
    for t in engine.tickets_of_bom(bomId):
        if t["obligation_type"] == "NOTICE_FILE" and t["status"] in ("OPEN", "IN_PROGRESS", "OVERDUE"):
            t["status"] = "FULFILLED"
            touch(t)
            entry = store.bom_entries.get(t["bom_entry_id"])
            if entry:
                engine.update_entry_obligation_fulfilled(entry)
    return success_obj(bom_view(bom))


@bp.route("/oss-products/<productId>/boms/<bomId>/archive", methods=["POST"])
def archive_bom(productId, bomId):
    require_roles("ComplianceAnalyst")
    p, bom, _ = _resolve(productId, bomId)
    if bom["status"] != "FINALIZED":
        raise err(ERR_BOM_NOT_ARCHIVABLE, "BOM has open ReleaseGates or no newer FINALIZED BOM exists")
    # No open ReleaseGates reference this BOM
    for g in store.gates.values():
        if g["bom_id"] == bomId and g["gate_status"] in ("OPEN", "EVALUATING"):
            raise err(ERR_BOM_NOT_ARCHIVABLE, "BOM has open ReleaseGates or no newer FINALIZED BOM exists")
    # Product has a newer FINALIZED BOM
    newer = [b for b in store.boms.values()
             if b["product_id"] == productId and b["id"] != bomId and b["status"] == "FINALIZED"
             and (b["created_at"], b["id"]) > (bom["created_at"], bom["id"])]
    if not newer:
        raise err(ERR_BOM_NOT_ARCHIVABLE, "BOM has open ReleaseGates or no newer FINALIZED BOM exists")
    bom["status"] = "ARCHIVED"
    touch(bom)
    return success_obj(bom_view(bom))
