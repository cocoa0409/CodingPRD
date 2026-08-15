"""PSI / P&ID documents: OCC-guarded issue with supersede, review cycle
(PRD 3.5, SCAFFOLD state_machines.PsidDocument, concurrency_rules)."""
from flask import Blueprint

import envelope
from errors import ApiError
from guards import (
    ALL_ROLES,
    apply_filters,
    body_row,
    endpoint,
    occ,
    paginate,
    pagination,
    path_row,
    req_enum,
    req_string,
)
from serialize import psid_out
from store import db, sorted_rows, touch

bp = Blueprint("psid", __name__)

CREATE_SCHEMA = (
    frozenset(
        ["system_id", "doc_type", "revision_label", "content_uri", "expected_system_version"]
    ),
    frozenset(
        ["system_id", "doc_type", "revision_label", "content_uri", "expected_system_version"]
    ),
)

STATUS_VALUES = ("CURRENT", "UNDER_REVIEW", "SUPERSEDED")


@bp.post("/psm/psid-documents")
@endpoint(["PsCoordinator"], schema=CREATE_SCHEMA)
def create_document(ctx):
    # step 0 -- payload values
    doc_type = req_enum(ctx.body, "doc_type")
    revision_label = req_string(ctx.body, "revision_label")
    content_uri = req_string(ctx.body, "content_uri")
    # step 3 -- existence
    system = body_row(ctx.body, "systems", "system_id")
    # step 4 -- OCC on RefrigerationSystem.version
    occ(ctx, "expected_system_version", system)
    # supersede the prior CURRENT / UNDER_REVIEW document for the same pair
    for other in db.psid_documents.values():
        if (
            other["system_id"] == system["id"]
            and other["doc_type"] == doc_type
            and other["status"] in ("CURRENT", "UNDER_REVIEW")
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    row = db.create(
        "psid_documents",
        {
            "system_id": system["id"],
            "doc_type": doc_type,
            "revision_label": revision_label,
            "content_uri": content_uri,
            "status": "CURRENT",
            "last_reaffirmed_at": None,
        },
    )
    touch(system)  # issuing a document increments the system's version by 1
    return envelope.created(psid_out(row))


@bp.get("/psm/psid-documents/<doc_id>")
@endpoint(ALL_ROLES)
def get_document(ctx, doc_id):
    return envelope.ok(psid_out(path_row("psid_documents", doc_id)))


@bp.get("/psm/psid-documents")
@endpoint(ALL_ROLES)
def list_documents(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.psid_documents.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("system_id", "system_id", None),
            ("doc_type", "doc_type", ("PID", "PSV_CALC", "RELIEF_DESIGN")),
            ("status", "status", STATUS_VALUES),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [psid_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )


@bp.post("/psm/psid-documents/<doc_id>/start-review")
@endpoint(["PsCoordinator"], schema=(frozenset(), frozenset()))
def start_review(ctx, doc_id):
    doc = path_row("psid_documents", doc_id)
    if doc["status"] != "CURRENT":
        raise ApiError("ERR_INVALID_STATE")
    doc["status"] = "UNDER_REVIEW"
    touch(doc)
    return envelope.ok(psid_out(doc))


@bp.post("/psm/psid-documents/<doc_id>/reaffirm")
@endpoint(["PsCoordinator"], schema=(frozenset(), frozenset()))
def reaffirm(ctx, doc_id):
    doc = path_row("psid_documents", doc_id)
    if doc["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    doc["status"] = "CURRENT"
    doc["last_reaffirmed_at"] = db.now()
    touch(doc)
    return envelope.ok(psid_out(doc))
