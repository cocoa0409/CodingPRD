"""CopySearchRequest routes (PRD §3.8, §4). Certified copies and name searches
with strict field-combination rules and index-driven fulfillment."""
from flask import Blueprint, request

import errors
import calculations as calc
from auth import require_auth, SUBMITTER, CLERK, ALL_READERS
from db import db, new_id, common_fields, touch
from helpers import (body, require_fields, as_str, as_enum, get_or_404, out,
                     out_list, paginate, sort_created)
from response import ok, created, listed

bp = Blueprint("copy_search", __name__)

REQUEST_TYPES = {"CERTIFIED_COPY", "NAME_SEARCH"}


@bp.route("/copy-search-requests", methods=["POST"])
def create_request():
    require_auth([SUBMITTER])
    data = body()
    require_fields(data, ["submitter_id", "request_type"])
    submitter_id = as_str(data, "submitter_id")
    request_type = as_enum(data, "request_type", REQUEST_TYPES)
    recorded_document_id = data.get("recorded_document_id")
    search_name = data.get("search_name")

    # Field-combination rule (priority 4, PRD §3.8): CERTIFIED_COPY must carry
    # recorded_document_id and must not carry search_name; NAME_SEARCH must
    # carry search_name and must not carry recorded_document_id.
    if request_type == "CERTIFIED_COPY":
        if not isinstance(recorded_document_id, str) or recorded_document_id == "":
            raise errors.err(errors.ERR_INVALID_REQUEST, "CERTIFIED_COPY requires recorded_document_id")
        if search_name is not None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "CERTIFIED_COPY must not carry search_name")
    else:  # NAME_SEARCH
        if not isinstance(search_name, str) or search_name == "":
            raise errors.err(errors.ERR_INVALID_REQUEST, "NAME_SEARCH requires search_name")
        if recorded_document_id is not None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "NAME_SEARCH must not carry recorded_document_id")

    # Existence (priority 3): submitter, and the recorded document for copies.
    get_or_404(db.submitters, submitter_id)
    if request_type == "CERTIFIED_COPY":
        get_or_404(db.recorded_documents, recorded_document_id)

    fee = calc.copy_search_fee_cents(request_type)

    rid = new_id()
    req = {
        "id": rid,
        "submitter_id": submitter_id,
        "request_type": request_type,
        "recorded_document_id": recorded_document_id if request_type == "CERTIFIED_COPY" else None,
        "search_name": search_name if request_type == "NAME_SEARCH" else None,
        "fee_cents": fee,
        "status": "REQUESTED",
        "result_count": None,
    }
    req.update(common_fields())
    db.copy_search_requests[rid] = req
    return created(out(req))


@bp.route("/copy-search-requests/<rid>", methods=["GET"])
def get_request(rid):
    require_auth(ALL_READERS)
    req = get_or_404(db.copy_search_requests, rid)
    return ok(out(req))


@bp.route("/copy-search-requests", methods=["GET"])
def list_requests():
    require_auth(ALL_READERS)
    items = list(db.copy_search_requests.values())
    submitter_id = request.args.get("submitter_id")
    recorded_document_id = request.args.get("recorded_document_id")
    request_type = request.args.get("request_type")
    status = request.args.get("status")
    if submitter_id is not None:
        items = [r for r in items if r["submitter_id"] == submitter_id]
    if recorded_document_id is not None:
        items = [r for r in items if r["recorded_document_id"] == recorded_document_id]
    if request_type is not None:
        items = [r for r in items if r["request_type"] == request_type]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


@bp.route("/copy-search-requests/<rid>/fulfill", methods=["POST"])
def fulfill_request(rid):
    require_auth([CLERK])
    req = get_or_404(db.copy_search_requests, rid)
    # State (priority 5)
    if req["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Request is not REQUESTED")

    if req["request_type"] == "CERTIFIED_COPY":
        # Cross-entity state (priority 8): referenced doc must exist and be RECORDED.
        doc = db.recorded_documents.get(req["recorded_document_id"])
        if doc is None or doc["status"] != "RECORDED":
            raise errors.err(errors.ERR_DOCUMENT_NOT_RECORDED, "Referenced document is not RECORDED")
        req["result_count"] = 1
    else:  # NAME_SEARCH
        count = 0
        for pe in db.party_entries.values():
            if pe["status"] == "INDEXED" and pe["party_name"] == req["search_name"]:
                count += 1
        req["result_count"] = count

    req["status"] = "FULFILLED"
    touch(req)
    return ok(out(req))


@bp.route("/copy-search-requests/<rid>/deny", methods=["POST"])
def deny_request(rid):
    require_auth([CLERK])
    req = get_or_404(db.copy_search_requests, rid)
    if req["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Request is not REQUESTED")
    req["status"] = "DENIED"
    touch(req)
    return ok(out(req))
