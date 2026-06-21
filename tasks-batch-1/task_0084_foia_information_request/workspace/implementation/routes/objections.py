"""Reverse-FOIA ThirdPartyObjection: open notice, object, resolve, lapse."""

from datetime import timedelta

from flask import Blueprint, g, request as flask_request

import db
import services
from clock import now, now_iso, parse_iso
from errors import (
    api_error,
    ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER, ERR_SUBMITTER_MISMATCH,
)
from helpers import (
    get_json_body, require_str, require_enum, get_or_404, fk_or_404,
    serialize, parse_pagination, sort_by_creation, paginate,
)
from middleware import require_roles
from response import ok_object, ok_array

bp = Blueprint("objections", __name__)

RESOLUTIONS = {"SUSTAIN", "OVERRULE"}


# ---- Open a Reverse-FOIA notice --------------------------------------------
@bp.post("/records/<rec_id>/objection")
def open_objection(rec_id):
    require_roles("FoiaOfficer")
    rec = get_or_404(db.records, rec_id)
    body = get_json_body()
    # Body-FK existence (priority 5) before remaining structural validity (6).
    submitter_id = require_str(body, "submitter_id")
    fk_or_404(db.submitters, submitter_id)
    objection_text = require_str(body, "objection_text")

    if rec.get("submitter_id") != submitter_id:
        raise api_error(ERR_SUBMITTER_MISMATCH, "submitter_id must equal the record's submitter_id.")

    obj = {
        "record_id": rec_id,
        "submitter_id": submitter_id,
        "notice_sent_at": now_iso(),
        "objection_text": objection_text,
        "status": "NOTICED",
    }
    db.stamp_create(obj)
    db.objections[obj["id"]] = obj
    services.append_audit(rec["request_id"], "REVERSE_NOTICE", "reverse-FOIA notice opened", "FoiaOfficer")
    return ok_object(serialize("ThirdPartyObjection", obj), status=201)


@bp.get("/objections/<oid>")
def get_objection(oid):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority", "Submitter")
    obj = get_or_404(db.objections, oid)
    return ok_object(serialize("ThirdPartyObjection", obj), status=200)


@bp.get("/objections")
def list_objections():
    require_roles("Requester", "FoiaOfficer", "AppealAuthority", "Submitter")
    limit, offset = parse_pagination()
    record_id = flask_request.args.get("record_id")
    submitter_id = flask_request.args.get("submitter_id")
    items = list(db.objections.values())
    if record_id is not None:
        items = [o for o in items if o["record_id"] == record_id]
    if submitter_id is not None:
        items = [o for o in items if o["submitter_id"] == submitter_id]
    items = sort_by_creation(items)
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("ThirdPartyObjection", o) for o in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


# ---- Submitter objects -----------------------------------------------------
@bp.post("/objections/<oid>/object")
def submitter_object(oid):
    require_roles("Submitter")
    obj = get_or_404(db.objections, oid)
    if obj["submitter_id"] != g.user_id:
        raise api_error(ERR_NOT_RESOURCE_OWNER, "Only the named submitter may object.")
    if obj["status"] != "NOTICED":
        raise api_error(ERR_INVALID_STATE, "Objection must be NOTICED to formally object.")
    obj["status"] = "OBJECTED"
    db.touch(obj)
    rec = db.records.get(obj["record_id"])
    if rec is not None:
        services.append_audit(rec["request_id"], "REVERSE_NOTICE", "submitter objected", "Submitter")
    return ok_object(serialize("ThirdPartyObjection", obj), status=200)


# ---- Officer resolves ------------------------------------------------------
@bp.post("/objections/<oid>/resolve")
def resolve_objection(oid):
    require_roles("FoiaOfficer")
    obj = get_or_404(db.objections, oid)
    body = get_json_body()
    resolution = require_enum(body, "resolution", RESOLUTIONS)
    if obj["status"] != "OBJECTED":
        raise api_error(ERR_INVALID_STATE, "Objection must be OBJECTED to resolve.")

    rec = db.records.get(obj["record_id"])
    if resolution == "SUSTAIN":
        obj["status"] = "SUSTAINED"
        db.touch(obj)
        if rec is not None:
            rec["disposition"] = "WITHHELD"
            db.touch(rec)
            # Create the citing exemption so the WITHHELD record has its citation.
            ex = {
                "request_id": rec["request_id"],
                "record_id": rec["id"],
                "applies_to_kind": "RECORD",
                "exemption_code": "B4",
                "justification": "Confidential commercial information (Reverse FOIA sustained).",
            }
            db.stamp_create(ex, versioned=False)
            db.exemptions[ex["id"]] = ex
            services.append_audit(rec["request_id"], "REVERSE_DECIDED",
                                  "objection sustained; record withheld", "FoiaOfficer")
    else:  # OVERRULE
        obj["status"] = "OVERRULED"
        db.touch(obj)
        if rec is not None:
            services.append_audit(rec["request_id"], "REVERSE_DECIDED",
                                  "objection overruled; disclosure permitted", "FoiaOfficer")
    return ok_object(serialize("ThirdPartyObjection", obj), status=200)


# ---- Officer lapses --------------------------------------------------------
@bp.post("/objections/<oid>/lapse")
def lapse_objection(oid):
    require_roles("FoiaOfficer")
    obj = get_or_404(db.objections, oid)
    if obj["status"] != "NOTICED":
        raise api_error(ERR_INVALID_STATE, "Objection must be NOTICED to lapse.")
    notice_at = parse_iso(obj["notice_sent_at"])
    if now() < notice_at + timedelta(days=services.REVERSE_NOTICE_DAYS):
        raise api_error(ERR_INVALID_STATE, "The reverse-notice window has not yet elapsed.")
    obj["status"] = "NO_RESPONSE"
    db.touch(obj)
    rec = db.records.get(obj["record_id"])
    if rec is not None:
        services.append_audit(rec["request_id"], "REVERSE_DECIDED",
                              "no timely objection; disclosure permitted", "FoiaOfficer")
    return ok_object(serialize("ThirdPartyObjection", obj), status=200)
