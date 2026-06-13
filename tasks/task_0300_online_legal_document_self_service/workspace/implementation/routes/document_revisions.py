"""DocumentRevision routes: OCC-guarded snapshot create + reads."""

from flask import Blueprint, request

import errors
import validators
from common import base_entity, get_or_404, list_collection, serialize, touch
from db import store
from middleware import get_json_body, parse_pagination, roles
from response import array_response, object_response

bp = Blueprint("document_revisions", __name__)


@bp.route("/legal/document-revisions", methods=["POST"])
@roles("Customer")
def create_revision():
    body = get_json_body()
    project_id = validators.require_string(body, "document_project_id")
    # OCC field is required and must be an integer (well-formedness, 400).
    expected_version = validators.require_int(body, "expected_document_project_version")

    # Existence (404).
    project = store.document_projects.get(project_id)
    if project is None:
        raise errors.not_found("document_project_id does not exist")

    # OCC (412) — precedes state validity per validation order (priority 6 < 7).
    if expected_version != project["version"]:
        raise errors.ApiError(errors.ERR_STALE_PROJECT_VERSION, 412,
                              "expected_document_project_version is stale")

    # Assign revision_number = 1-based sequence within the project (created_at ASC).
    siblings = [
        r for r in store.document_revisions.values()
        if r["document_project_id"] == project_id
    ]
    revision_number = len(siblings) + 1

    # Flip prior FINAL revisions of this project to SUPERSEDED.
    for r in siblings:
        if r["status"] == "FINAL":
            r["status"] = "SUPERSEDED"
            touch(r)

    # clause_snapshot_count = number of AssembledClause rows for the project.
    clause_count = sum(
        1 for c in store.assembled_clauses.values()
        if c["document_project_id"] == project_id
    )

    ent = base_entity()
    ent.update({
        "document_project_id": project_id,
        "expected_document_project_version": expected_version,
        "revision_number": revision_number,
        "clause_snapshot_count": clause_count,
        "status": "FINAL",
    })
    store.document_revisions[ent["id"]] = ent

    # Creating a revision advances the project version by one.
    touch(project)

    return object_response(serialize(ent), 201)


@bp.route("/legal/document-revisions/<rid>", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def get_revision(rid):
    ent = get_or_404(store.document_revisions, rid)
    return object_response(serialize(ent), 200)


@bp.route("/legal/document-revisions", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def list_revisions():
    limit, offset = parse_pagination()
    project_id = request.args.get("document_project_id")

    def predicate(e):
        if project_id is not None and e["document_project_id"] != project_id:
            return False
        return True

    page, total = list_collection(store.document_revisions, predicate, limit, offset)
    return array_response(page, limit, offset, total, 200)
