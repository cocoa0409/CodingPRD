"""Document record endpoints (PRD 3.9)."""

from flask import Blueprint

import clock
import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import (
    new_entity, touch, get_document_or_404, add_years,
    ARTIFACT_TYPES, RELATED_ENTITY_TYPES, RETENTION_YEARS,
)

bp = Blueprint("documents", __name__)


def document_view(d):
    return {
        "id": d["id"],
        "artifact_type": d["artifact_type"],
        "related_entity_type": d["related_entity_type"],
        "related_entity_id": d["related_entity_id"],
        "retention_until": d["retention_until"].isoformat(),
        "purged_at": d["purged_at"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.post("/escheatment/document-records")
def create_document():
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    data = mw.body_json()
    artifact_type = mw.req_enum(data, "artifact_type", ARTIFACT_TYPES)
    related_type = mw.req_enum(data, "related_entity_type", RELATED_ENTITY_TYPES)
    related_id = mw.req_string(data, "related_entity_id")
    creation_date = clock.today()
    retention_until = add_years(creation_date, RETENTION_YEARS[artifact_type])
    doc = new_entity({
        "artifact_type": artifact_type,
        "related_entity_type": related_type,
        "related_entity_id": related_id,
        "retention_until": retention_until,
        "purged_at": None,
        "status": "REGISTERED",
    })
    db.document_records[doc["id"]] = doc
    return resp.success(document_view(doc), "object", 201)


@bp.get("/escheatment/document-records")
def list_documents():
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    limit, offset = mw.pagination_params()
    items = list(db.document_records.values())
    artifact_type = mw.request.args.get("artifact_type")
    if artifact_type is not None:
        items = [d for d in items if d["artifact_type"] == artifact_type]
    include_purged = mw.request.args.get("include_purged", "").lower() == "true"
    if not include_purged:
        items = [d for d in items if d["status"] != "PURGED"]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([document_view(d) for d in page], "array", 200, pagination=meta)


@bp.get("/escheatment/document-records/<docId>")
def get_document(docId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    doc = get_document_or_404(docId)
    return resp.success(document_view(doc), "object", 200)


@bp.post("/escheatment/document-records/<docId>/purge")
def purge_document(docId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("HolderAdmin",))
    mw.body_json(required=False)
    doc = get_document_or_404(docId)
    if doc["status"] != "REGISTERED":
        raise_error(errors.ERR_DOCUMENT_ALREADY_PURGED, "The record is already PURGED")
    # Purge allowed exactly on retention_until; earlier is refused.
    if clock.today() < doc["retention_until"]:
        raise_error(
            errors.ERR_RETENTION_PERIOD_NOT_ELAPSED,
            "The retention period has not fully elapsed",
        )
    doc["status"] = "PURGED"
    doc["purged_at"] = clock.now_iso()
    touch(doc)
    return resp.success(document_view(doc), "object", 200)
