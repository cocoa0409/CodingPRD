"""IngestBatch, Asset and ProxyRendition routes (intake and cataloging)."""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, require_roles
from db import STORE, new_id, now, stamp
from envelope import ok, paginate
from errors import raise_err
from serializers import asset_out, batch_out, proxy_out
from validate import (
    CONTENT_RATINGS, FORMAT_CLASSES, MEDIA_TYPES, RENDITION_TYPES,
    body, opt_enum, opt_str_list, req_enum, req_int, req_num, req_str,
)

bp = Blueprint("ingest", __name__, url_prefix="/archive")


def _get_batch(bid):
    rec = STORE.batches.get(bid)
    if rec is None:
        raise_err("ERR_BATCH_NOT_FOUND", "Ingest batch not found")
    return rec


def _get_asset(aid):
    rec = STORE.assets.get(aid)
    if rec is None:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    return rec


def _get_proxy(pid):
    rec = STORE.proxies.get(pid)
    if rec is None:
        raise_err("ERR_PROXY_NOT_FOUND", "Proxy rendition not found")
    return rec


# --- IngestBatch -------------------------------------------------------------
@bp.post("/ingest-batches")
def create_batch():
    require_roles("IngestCoordinator")
    j = body()
    batch_name = req_str(j, "batch_name")
    source_department = req_str(j, "source_department")
    rec = {
        "id": new_id(),
        "batch_name": batch_name,
        "source_department": source_department,
        "status": "OPEN",
    }
    stamp(rec)
    STORE.batches[rec["id"]] = rec
    return ok(batch_out(rec), 201)


@bp.get("/ingest-batches")
def list_batches():
    require_roles(*ALL_ROLES)
    recs = list(STORE.batches.values())
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, batch_out)


@bp.get("/ingest-batches/<bid>")
def get_batch(bid):
    require_roles(*ALL_ROLES)
    return ok(batch_out(_get_batch(bid)))


@bp.post("/ingest-batches/<bid>/finalize")
def finalize_batch(bid):
    require_roles("IngestCoordinator")
    rec = _get_batch(bid)
    if rec["status"] != "OPEN":
        raise_err("ERR_BATCH_NOT_OPEN", "Batch is not OPEN")
    assets = [a for a in STORE.assets.values() if a["ingest_batch_id"] == bid]
    if not assets:
        raise_err("ERR_EMPTY_BATCH", "Cannot finalize a batch with zero assets")
    if any(a["catalog_status"] == "METADATA_DRAFT" for a in assets):
        raise_err(
            "ERR_BATCH_ASSETS_UNRESOLVED",
            "Some assets in the batch are still METADATA_DRAFT",
        )
    rec["status"] = "FINALIZED"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(batch_out(rec))


# --- Asset -------------------------------------------------------------------
@bp.post("/assets")
def create_asset():
    require_roles("IngestCoordinator")
    j = body()
    # FK presence/type first so the reference can be resolved
    ingest_batch_id = req_str(j, "ingest_batch_id")
    batch = STORE.batches.get(ingest_batch_id)
    if batch is None:
        raise_err("ERR_BATCH_NOT_FOUND", "Ingest batch not found")
    # State precondition
    if batch["status"] != "OPEN":
        raise_err("ERR_BATCH_NOT_OPEN", "Assets may only be ingested into an OPEN batch")
    # Remaining shape validation
    title = req_str(j, "title")
    description = req_str(j, "description")
    media_type = req_enum(j, "media_type", MEDIA_TYPES)
    format_class = req_enum(j, "format_class", FORMAT_CLASSES)
    duration_seconds = req_int(j, "duration_seconds", positive=True)
    size_gb = req_num(j, "size_gb", positive=True)
    rights_holder = req_str(j, "rights_holder")
    keywords = opt_str_list(j, "keywords", [])
    content_rating = opt_enum(j, "content_rating", CONTENT_RATINGS, "NR")
    rec = {
        "id": new_id(),
        "ingest_batch_id": ingest_batch_id,
        "source_asset_id": None,
        "title": title,
        "description": description,
        "media_type": media_type,
        "format_class": format_class,
        "duration_seconds": duration_seconds,
        "size_gb": size_gb,
        "rights_holder": rights_holder,
        "keywords": keywords,
        "content_rating": content_rating,
        "catalog_status": "METADATA_DRAFT",
        "storage_tier": "ONLINE",
        "metadata_submitted_by_user_id": None,
    }
    stamp(rec)
    STORE.assets[rec["id"]] = rec
    return ok(asset_out(rec), 201)


@bp.get("/assets")
def list_assets():
    require_roles(*ALL_ROLES)
    recs = list(STORE.assets.values())
    for param, field in (
        ("ingest_batch_id", "ingest_batch_id"),
        ("source_asset_id", "source_asset_id"),
        ("catalog_status", "catalog_status"),
        ("storage_tier", "storage_tier"),
        ("format_class", "format_class"),
    ):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    return paginate(recs, asset_out)


@bp.get("/assets/<aid>")
def get_asset(aid):
    require_roles(*ALL_ROLES)
    return ok(asset_out(_get_asset(aid)))


@bp.patch("/assets/<aid>")
def patch_asset(aid):
    require_roles("MetadataCataloger")
    rec = _get_asset(aid)
    j = body()
    # Shape of supplied fields (wrong types are malformed)
    if "title" in j:
        req_str(j, "title")
    if "description" in j:
        req_str(j, "description")
    if "keywords" in j:
        opt_str_list(j, "keywords", [])
    if "content_rating" in j:
        opt_enum(j, "content_rating", CONTENT_RATINGS, "NR")
    if "rights_holder" in j:
        req_str(j, "rights_holder")
    # State: editable only in METADATA_DRAFT or IN_REVIEW
    if rec["catalog_status"] not in ("METADATA_DRAFT", "IN_REVIEW"):
        raise_err("ERR_ASSET_LOCKED", "Asset metadata is locked outside METADATA_DRAFT/IN_REVIEW")
    for field in ("title", "description", "keywords", "content_rating", "rights_holder"):
        if field in j:
            rec[field] = j[field]
    rec["version"] += 1
    rec["updated_at"] = now()
    return ok(asset_out(rec))


@bp.post("/assets/<aid>/submit-metadata")
def submit_metadata(aid):
    uid, _ = require_roles("MetadataCataloger")
    rec = _get_asset(aid)
    if rec["catalog_status"] != "METADATA_DRAFT":
        raise_err("ERR_INVALID_CATALOG_TRANSITION", "submit-metadata requires METADATA_DRAFT")
    if (
        not rec["description"]
        or len(rec["keywords"]) < 1
        or rec["content_rating"] == "NR"
    ):
        raise_err(
            "ERR_METADATA_INCOMPLETE",
            "description must be non-empty, keywords must have >= 1 entry, "
            "content_rating must not be NR",
        )
    rec["catalog_status"] = "IN_REVIEW"
    rec["metadata_submitted_by_user_id"] = uid
    rec["version"] += 1
    rec["updated_at"] = now()
    return ok(asset_out(rec))


@bp.post("/assets/<aid>/metadata-approve")
def metadata_approve(aid):
    uid, _ = require_roles("MetadataLibrarian")
    rec = _get_asset(aid)
    if rec["catalog_status"] != "IN_REVIEW":
        raise_err("ERR_INVALID_CATALOG_TRANSITION", "metadata-approve requires IN_REVIEW")
    if uid == rec["metadata_submitted_by_user_id"]:
        raise_err("ERR_SOD_METADATA_SELF_APPROVE", "Approver must differ from the submitter")
    rec["catalog_status"] = "CATALOGED"
    rec["version"] += 1
    rec["updated_at"] = now()
    return ok(asset_out(rec))


@bp.post("/assets/<aid>/metadata-reject")
def metadata_reject(aid):
    require_roles("MetadataLibrarian")
    rec = _get_asset(aid)
    if rec["catalog_status"] != "IN_REVIEW":
        raise_err("ERR_INVALID_CATALOG_TRANSITION", "metadata-reject requires IN_REVIEW")
    j = body()
    req_str(j, "reason")
    rec["catalog_status"] = "METADATA_DRAFT"
    rec["metadata_submitted_by_user_id"] = None
    rec["version"] += 1
    rec["updated_at"] = now()
    return ok(asset_out(rec))


@bp.post("/assets/<aid>/archive")
def archive_asset(aid):
    require_roles("ArchivistLead")
    rec = _get_asset(aid)
    if rec["catalog_status"] != "CATALOGED":
        raise_err("ERR_INVALID_CATALOG_TRANSITION", "archive requires CATALOGED")
    if not any(
        p["asset_id"] == aid and p["status"] == "READY" for p in STORE.proxies.values()
    ):
        raise_err("ERR_PROXY_NOT_READY", "At least one READY proxy rendition is required")
    if not any(g["asset_id"] == aid for g in STORE.grants.values()):
        raise_err("ERR_NO_RIGHTS_GRANT_ON_RECORD", "At least one rights grant must be on record")
    rec["catalog_status"] = "ARCHIVED"
    rec["version"] += 1
    rec["updated_at"] = now()
    return ok(asset_out(rec))


@bp.post("/assets/<aid>/recatalog")
def recatalog_asset(aid):
    require_roles("ArchivistLead")
    rec = _get_asset(aid)
    if rec["catalog_status"] != "ARCHIVED":
        raise_err("ERR_INVALID_CATALOG_TRANSITION", "recatalog requires ARCHIVED")
    rec["catalog_status"] = "IN_REVIEW"
    rec["metadata_submitted_by_user_id"] = None
    rec["version"] += 1
    rec["updated_at"] = now()
    return ok(asset_out(rec))


@bp.get("/assets/<aid>/storage-cost")
def storage_cost(aid):
    require_roles("SystemAdmin", "ArchivistLead", "FinanceOfficer")
    rec = _get_asset(aid)
    projected, actual = calc.storage_cost(rec)
    return ok({
        "projected_cost_cents": projected,
        "actual_cost_cents": actual,
        "currency": "USD",
    })


# --- ProxyRendition -----------------------------------------------------------
@bp.post("/proxy-renditions")
def create_proxy():
    require_roles("IngestCoordinator", "LabTechnician")
    j = body()
    asset_id = req_str(j, "asset_id")
    if asset_id not in STORE.assets:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    rendition_type = opt_enum(j, "rendition_type", RENDITION_TYPES, "PROXY_LOWRES")
    rec = {
        "id": new_id(),
        "asset_id": asset_id,
        "rendition_type": rendition_type,
        "status": "QUEUED",
        "retry_count": 0,
        "proxy_url": None,
        "indexed_at": None,
        "failure_reason": None,
    }
    stamp(rec)
    STORE.proxies[rec["id"]] = rec
    return ok(proxy_out(rec), 201)


@bp.get("/proxy-renditions")
def list_proxies():
    require_roles(*ALL_ROLES)
    recs = list(STORE.proxies.values())
    for param, field in (("asset_id", "asset_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    return paginate(recs, proxy_out)


@bp.get("/proxy-renditions/<pid>")
def get_proxy(pid):
    require_roles(*ALL_ROLES)
    return ok(proxy_out(_get_proxy(pid)))


@bp.post("/proxy-renditions/<pid>/claim")
def claim_proxy(pid):
    require_roles("LabTechnician")
    rec = _get_proxy(pid)
    if rec["status"] != "QUEUED":
        raise_err("ERR_PROXY_NOT_QUEUED", "claim requires QUEUED")
    rec["status"] = "RENDERING"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(proxy_out(rec))


@bp.post("/proxy-renditions/<pid>/complete")
def complete_proxy(pid):
    require_roles("LabTechnician")
    rec = _get_proxy(pid)
    if rec["status"] != "RENDERING":
        raise_err("ERR_PROXY_NOT_RENDERING", "complete requires RENDERING")
    rec["status"] = "READY"
    rec["proxy_url"] = f"proxy://renditions/{rec['id']}"
    rec["indexed_at"] = now()
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(proxy_out(rec))


@bp.post("/proxy-renditions/<pid>/fail")
def fail_proxy(pid):
    require_roles("LabTechnician")
    rec = _get_proxy(pid)
    if rec["status"] != "RENDERING":
        raise_err("ERR_PROXY_NOT_RENDERING", "fail requires RENDERING")
    j = body()
    reason = req_str(j, "reason")
    rec["status"] = "FAILED"
    rec["failure_reason"] = reason
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(proxy_out(rec))


@bp.post("/proxy-renditions/<pid>/retry")
def retry_proxy(pid):
    require_roles("LabTechnician")
    rec = _get_proxy(pid)
    if rec["status"] != "FAILED":
        raise_err("ERR_PROXY_NOT_FAILED", "retry requires FAILED")
    if rec["retry_count"] >= calc.MAX_PROXY_RETRIES:
        raise_err("ERR_RETRY_BUDGET_EXHAUSTED", "Proxy retry budget exhausted (cap 3)")
    rec["status"] = "QUEUED"
    rec["retry_count"] += 1
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(proxy_out(rec))
