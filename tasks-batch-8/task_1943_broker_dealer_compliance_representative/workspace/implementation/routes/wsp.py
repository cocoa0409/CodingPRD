"""WSPDocument endpoints (PRD 3.9): per-area versioning + publish/singleton."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_SOD_WSP_PUBLISHER,
    ERR_WSP_NOT_DRAFT,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import by_creation, new_record, public, touch
from validate import get_body, req_date, req_enum, req_str, require_path_resource

bp = Blueprint("wsp", __name__)

POLICY_AREAS = ("CORRESPONDENCE", "OBA_PST", "COMPLAINTS", "DISCLOSURE",
                "HEIGHTENED_SUPERVISION", "INSPECTIONS", "BOOKS_RECORDS")


@bp.post("/wsp-documents")
def create_wsp():
    caller = authorized(["ComplianceAnalyst"])
    body = get_body()
    policy_area = req_enum(body, "policy_area", POLICY_AREAS)
    title = req_str(body, "title")
    effective_date = req_date(body, "effective_date")

    # version_number = 1 + max(version_number) within the policy area, else 1
    existing = [d for d in db["wsp_documents"].values()
                if d["policy_area"] == policy_area]
    version_number = 1 + max((d["version_number"] for d in existing), default=0)

    rec = new_record("wsp_documents", {
        "policy_area": policy_area,
        "title": title,
        "effective_date": effective_date,
        "version_number": version_number,
        "drafted_by": caller.user_id,
        "published_by": None,
        "supersedes_id": None,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/wsp-documents")
def list_wsp():
    return list_response("wsp_documents", filters={
        "policy_area": request.args.get("policy_area"),
        "status": request.args.get("status"),
        "supersedes_id": request.args.get("supersedes_id"),
    })


@bp.get("/wsp-documents/<rid>")
def get_wsp(rid):
    return get_one("wsp_documents", rid)


@bp.post("/wsp-documents/<rid>/publish")
def publish_wsp(rid):
    caller = authorized(["CompliancePrincipal"])
    doc = require_path_resource("wsp_documents", rid)
    if doc["status"] != "DRAFT":
        raise_error(ERR_WSP_NOT_DRAFT, "publish is allowed only from DRAFT")
    # Segregation of duties (PRD 2.6): publisher must differ from the drafter
    if caller.user_id == doc["drafted_by"]:
        raise_error(ERR_SOD_WSP_PUBLISHER,
                    "the drafting analyst cannot publish their own document")

    # Singleton invariant: the area's current PUBLISHED document (unique by
    # invariant) is superseded atomically with this publish.
    current = None
    for d in db["wsp_documents"].values():
        if (d["policy_area"] == doc["policy_area"] and d["status"] == "PUBLISHED"
                and d["id"] != doc["id"]):
            current = d
            break
    if current is not None:
        current["status"] = "SUPERSEDED"
        touch(current)
    doc["supersedes_id"] = current["id"] if current is not None else None
    doc["published_by"] = caller.user_id
    doc["status"] = "PUBLISHED"
    touch(doc)
    return success_object(public(doc))
