"""ValidityDossier endpoints (PRD §3.9)."""
from flask import Blueprint, request

from db import db, next_seq
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_DOSSIER_INVALID,
    ERR_DOSSIER_NOT_DRAFT,
    ERR_DOSSIER_NOT_PUBLISHED,
    ERR_DOSSIER_FORM_NOT_FINAL,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.common import touch
from util import new_id, now_ts, program_clock_iso
from validate import get_body, req_str, require_path_resource, require_body_ref

bp = Blueprint("dossiers", __name__)

DOSSIER_KINDS = ["TECHNICAL_MANUAL", "VALIDITY_EVIDENCE", "RELIABILITY_REPORT"]
READ_ROLES = ["ProgramDirector", "Psychometrician", "TestAssembler"]
FINAL_FORM_STATUSES = ("ASSEMBLED", "EQUATED", "PUBLISHED")


@bp.post("/api/validity-dossiers")
def create_dossier():
    caller = authorized(["Psychometrician"])
    body = get_body()
    program_id = req_str(body, "program_id")
    form_id = req_str(body, "form_id")
    dossier_kind = body.get("dossier_kind")
    content_md = req_str(body, "content_md")

    require_body_ref("assessment_programs", program_id, "program_id")

    # §1.4 validation 18: kind validity, form existence, and content length all
    # surface as ERR_DOSSIER_INVALID (422).
    if not isinstance(dossier_kind, str) or dossier_kind not in DOSSIER_KINDS:
        raise_error(ERR_DOSSIER_INVALID, "dossier_kind is not a valid value")
    form = db["test_forms"].get(form_id)
    if form is None:
        raise_error(ERR_DOSSIER_INVALID, "form_id does not reference an existing form")
    if len(content_md) < 200:
        raise_error(ERR_DOSSIER_INVALID, "content_md must be at least 200 characters")

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "program_id": program_id,
        "form_id": form_id,
        "dossier_kind": dossier_kind,
        "content_md": content_md,
        "status": "DRAFT",
        "published_at": None,
        "_seq": next_seq(),
    }
    db["validity_dossiers"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/api/validity-dossiers")
def list_dossiers():
    authorized(READ_ROLES)
    filters = {
        "program_id": request.args.get("program_id"),
        "form_id": request.args.get("form_id"),
        "status": request.args.get("status"),
    }
    return list_response("validity_dossiers", filters)


@bp.get("/api/validity-dossiers/<vid>")
def get_dossier(vid):
    authorized(READ_ROLES)
    rec = require_path_resource("validity_dossiers", vid)
    return get_one(rec)


@bp.post("/api/validity-dossiers/<vid>/publish")
def publish_dossier(vid):
    caller = authorized(["Psychometrician"])
    rec = require_path_resource("validity_dossiers", vid)
    get_body()
    if rec["status"] != "DRAFT":
        raise_error(ERR_DOSSIER_NOT_DRAFT, "dossier must be DRAFT to publish")
    form = db["test_forms"].get(rec["form_id"])
    if form is None or form["status"] not in FINAL_FORM_STATUSES:
        raise_error(ERR_DOSSIER_FORM_NOT_FINAL, "dossier's form must be ASSEMBLED, EQUATED, or PUBLISHED")
    program = db["assessment_programs"].get(rec["program_id"])
    rec["status"] = "PUBLISHED"
    rec["published_at"] = program_clock_iso(program)
    touch(rec)
    return success_object(public(rec))


@bp.post("/api/validity-dossiers/<vid>/supersede")
def supersede_dossier(vid):
    caller = authorized(["Psychometrician"])
    rec = require_path_resource("validity_dossiers", vid)
    get_body()
    if rec["status"] != "PUBLISHED":
        raise_error(ERR_DOSSIER_NOT_PUBLISHED, "dossier must be PUBLISHED to supersede")
    rec["status"] = "SUPERSEDED"
    touch(rec)
    return success_object(public(rec))
