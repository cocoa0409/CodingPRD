"""ResponsiveRecord logging, review, and Exemption assertion."""

from flask import Blueprint, g, request as flask_request

import db
import services
from errors import (
    api_error,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SUBMITTER_MISMATCH,
    ERR_EXEMPTION_REQUIRED, ERR_REVERSE_FOIA_PENDING, ERR_INVALID_EXEMPTION_CODE,
)
from helpers import (
    get_json_body, require_str, require_int, require_bool, opt_str, require_enum,
    get_or_404, fk_or_404, serialize, parse_pagination, sort_by_creation, paginate,
)
from middleware import require_roles
from response import ok_object, ok_array

bp = Blueprint("records", __name__)

DISPOSITIONS = {"RELEASABLE", "REDACTED", "WITHHELD"}
EXEMPTION_CODES = {"B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9"}
EXEMPTION_KINDS = {"RECORD", "REQUEST"}
GLOMAR_CODES = {"B1", "B7"}


# ---- Log a record ----------------------------------------------------------
@bp.post("/requests/<rid>/records")
def log_record(rid):
    require_roles("FoiaOfficer")
    req = get_or_404(db.requests, rid)
    body = get_json_body()
    # Body-FK existence (priority 5) before remaining structural validity (6).
    submitter_id = opt_str(body, "submitter_id")
    if submitter_id is not None:
        fk_or_404(db.submitters, submitter_id)
    title = require_str(body, "title")
    page_count = require_int(body, "page_count", minimum=1)
    contains_submitter_info = require_bool(body, "contains_submitter_info", default=False)

    if req["status"] != "PROCESSING":
        raise api_error(ERR_INVALID_STATE, "Records may only be logged while the request is PROCESSING.")

    if contains_submitter_info and submitter_id is None:
        raise api_error(ERR_SUBMITTER_MISMATCH, "A submitter-info record must carry a submitter_id.")

    obj = {
        "request_id": rid,
        "title": title,
        "page_count": page_count,
        "contains_submitter_info": contains_submitter_info,
        "submitter_id": submitter_id,
        "disposition": "PENDING",
    }
    db.stamp_create(obj)
    db.records[obj["id"]] = obj
    return ok_object(serialize("ResponsiveRecord", obj), status=201)


@bp.get("/requests/<rid>/records")
def list_request_records(rid):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    get_or_404(db.requests, rid)
    limit, offset = parse_pagination()
    items = sort_by_creation([r for r in db.records.values() if r["request_id"] == rid])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("ResponsiveRecord", r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


@bp.get("/records/<rec_id>")
def get_record(rec_id):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    obj = get_or_404(db.records, rec_id)
    return ok_object(serialize("ResponsiveRecord", obj), status=200)


@bp.get("/records")
def list_records():
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    limit, offset = parse_pagination()
    submitter_id = flask_request.args.get("submitter_id")
    request_id = flask_request.args.get("request_id")
    items = list(db.records.values())
    if submitter_id is not None:
        items = [r for r in items if r["submitter_id"] == submitter_id]
    if request_id is not None:
        items = [r for r in items if r["request_id"] == request_id]
    items = sort_by_creation(items)
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("ResponsiveRecord", r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


# ---- Review a record -------------------------------------------------------
@bp.post("/records/<rec_id>/review")
def review_record(rec_id):
    require_roles("FoiaOfficer")
    rec = get_or_404(db.records, rec_id)
    body = get_json_body()
    disposition = require_enum(body, "disposition", DISPOSITIONS)

    req = db.requests.get(rec["request_id"])
    if req is None or req["status"] != "PROCESSING":
        raise api_error(ERR_INVALID_STATE, "Parent request must be PROCESSING to review a record.")
    if rec["disposition"] != "PENDING":
        raise api_error(ERR_INVALID_STATE, "Record must be PENDING to set its disposition.")

    has_exemption = services.record_has_record_exemption(rec_id)

    if disposition in ("REDACTED", "WITHHELD"):
        if not has_exemption:
            raise api_error(ERR_EXEMPTION_REQUIRED,
                            "A redacted/withheld record must be cited by an exemption.")
    else:  # RELEASABLE
        if has_exemption:
            raise api_error(ERR_EXEMPTION_REQUIRED,
                            "A record cited by an exemption cannot be made RELEASABLE.")
        # Reverse-FOIA gate.
        if rec.get("contains_submitter_info"):
            obj = services.objection_for_record(rec_id)
            if obj is not None and obj["status"] in ("NOTICED", "OBJECTED"):
                raise api_error(ERR_REVERSE_FOIA_PENDING,
                                "Cannot release a submitter-info record with a pending objection.")

    rec["disposition"] = disposition
    db.touch(rec)
    return ok_object(serialize("ResponsiveRecord", rec), status=200)


# ---- Exemptions ------------------------------------------------------------
@bp.post("/requests/<rid>/exemptions")
def assert_exemption(rid):
    require_roles("FoiaOfficer")
    req = get_or_404(db.requests, rid)
    body = get_json_body()
    # Body-FK existence (priority 5) before remaining structural validity (6)
    # and the exemption-code rule (priority 12).
    record_id = opt_str(body, "record_id")
    if record_id is not None:
        fk_or_404(db.records, record_id)
    applies_to_kind = require_enum(body, "applies_to_kind", EXEMPTION_KINDS)
    # exemption_code structural validity is ERR_INVALID_REQUEST only if not a
    # string; the B1..B9 / Glomar-set rule is the dedicated ERR_INVALID_EXEMPTION_CODE.
    code = body.get("exemption_code")
    if not isinstance(code, str):
        raise api_error(ERR_INVALID_REQUEST, "exemption_code must be a string.")
    justification = require_str(body, "justification")

    if code not in EXEMPTION_CODES:
        raise api_error(ERR_INVALID_EXEMPTION_CODE, "exemption_code must be one of B1..B9.")
    if applies_to_kind == "REQUEST" and code not in GLOMAR_CODES:
        raise api_error(ERR_INVALID_EXEMPTION_CODE, "REQUEST-level exemptions must be B1 or B7.")

    obj = {
        "request_id": rid,
        "record_id": record_id if applies_to_kind == "RECORD" else None,
        "applies_to_kind": applies_to_kind,
        "exemption_code": code,
        "justification": justification,
    }
    db.stamp_create(obj, versioned=False)
    db.exemptions[obj["id"]] = obj
    return ok_object(serialize("Exemption", obj), status=201)


@bp.get("/requests/<rid>/exemptions")
def list_request_exemptions(rid):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    get_or_404(db.requests, rid)
    limit, offset = parse_pagination()
    items = sort_by_creation([e for e in db.exemptions.values() if e["request_id"] == rid])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("Exemption", e) for e in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


@bp.get("/exemptions/<ex_id>")
def get_exemption(ex_id):
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    obj = get_or_404(db.exemptions, ex_id)
    return ok_object(serialize("Exemption", obj), status=200)


@bp.get("/exemptions")
def list_exemptions():
    require_roles("Requester", "FoiaOfficer", "AppealAuthority")
    limit, offset = parse_pagination()
    record_id = flask_request.args.get("record_id")
    request_id = flask_request.args.get("request_id")
    items = list(db.exemptions.values())
    if record_id is not None:
        items = [e for e in items if e["record_id"] == record_id]
    if request_id is not None:
        items = [e for e in items if e["request_id"] == request_id]
    items = sort_by_creation(items)
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize("Exemption", e) for e in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)
