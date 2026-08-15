"""Disclosure publication endpoints: create draft, publish, list, get."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from validation import require_path_entity

bp = Blueprint("disclosures", __name__)


@bp.post("/v1/reporting-cycles/<cycle_id>/disclosure-publications")
def create_publication(cycle_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    cycle = require_path_entity(store.cycles, cycle_id)
    if cycle["status"] not in ("FILING_CLOSED", "PUBLISHED"):
        raise ApiError("ERR_CYCLE_NOT_CLOSED", 409,
                       "Disclosure publication requires the cycle to be FILING_CLOSED "
                       "or PUBLISHED")
    max_version = 0
    for p in store.publications.values():
        if p["cycle_id"] != cycle["id"]:
            continue
        if p["status"] == "DRAFT":
            raise ApiError("ERR_DRAFT_PUBLICATION_EXISTS", 409,
                           "A DRAFT disclosure publication already exists for this cycle")
        max_version = max(max_version, p["publication_version"])
    publication = db.new_common({
        "id": db.new_id(),
        "cycle_id": cycle["id"],
        "publication_version": max_version + 1,
        "status": "DRAFT",
        "included_report_count": 0,
        "published_at": None,
        "superseded_at": None,
        "_included_report_ids": [],
    })
    store.publications[publication["id"]] = publication
    return created(publication)


@bp.post("/v1/disclosure-publications/<pub_id>/publish")
def publish_publication(pub_id):
    get_context()
    require_roles(["ComplianceOfficer"])
    pub = require_path_entity(store.publications, pub_id)
    if pub["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a DRAFT publication can be published")
    cycle = store.cycles.get(pub["cycle_id"])
    if cycle["status"] not in ("FILING_CLOSED", "PUBLISHED"):
        raise ApiError("ERR_CYCLE_NOT_CLOSED", 409,
                       "Publishing requires the cycle to be FILING_CLOSED or PUBLISHED")
    included = [r for r in store.reports.values()
                if r["cycle_id"] == cycle["id"] and r["status"] in ("VERIFIED", "CERTIFIED")]
    pub["status"] = "PUBLISHED"
    pub["published_at"] = db.LOGICAL_CLOCK
    pub["included_report_count"] = len(included)
    pub["_included_report_ids"] = [r["id"] for r in included]
    db.touch(pub)
    if cycle["status"] == "FILING_CLOSED":
        cycle["status"] = "PUBLISHED"
        cycle["published_at"] = db.LOGICAL_CLOCK
        db.touch(cycle)
    return ok(pub)


@bp.get("/v1/disclosure-publications")
def list_publications():
    get_context()
    rows = list(store.publications.values())
    rows = paginate.filter(rows, "cycle_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/v1/disclosure-publications/<pub_id>")
def get_publication(pub_id):
    get_context()
    pub = require_path_entity(store.publications, pub_id)
    return ok(pub)
