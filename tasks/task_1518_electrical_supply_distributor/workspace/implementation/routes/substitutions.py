"""SubstitutionRequest endpoints (PRD §3.5)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from db import new_record, sort_key, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_QUOTE_LINE_NOT_FOUND,
    ERR_CATALOG_ITEM_NOT_FOUND,
    ERR_SUBSTITUTION_REQUEST_NOT_FOUND,
    ERR_SUBSTITUTION_NOT_PROPOSED,
    ERR_QUOTE_NOT_DRAFT,
)
from middleware import ROLES, atomic, require_roles
from response import success_list, success_object
from serializers import ser_substitution_request
from util import get_json_body, paginate, require_string

bp = Blueprint("substitutions", __name__, url_prefix="/distributor")


def _query_arg(name: str):
    value = request.args.get(name)
    return value if value not in (None, "") else None


@bp.post("/substitution-requests")
@require_roles("SalesRep")
@atomic
def create_substitution_request():
    body = get_json_body()
    quote_line_id = require_string(body, "quote_line_id")
    proposed_item_id = require_string(body, "proposed_item_id")
    reason = require_string(body, "reason")

    line = db.quote_lines.get(quote_line_id)
    if line is None:
        raise_err(ERR_QUOTE_LINE_NOT_FOUND, "No quote line with the given id")
    item = db.catalog_items.get(proposed_item_id)
    if item is None:
        raise_err(ERR_CATALOG_ITEM_NOT_FOUND, "No catalog item with the given id")

    quote = db.quotes[line["quote_id"]]
    if quote["status"] != "DRAFT":
        raise_err(ERR_QUOTE_NOT_DRAFT, "Substitution requires the owning quote in DRAFT")

    sub = new_record(
        {
            "quote_line_id": quote_line_id,
            "proposed_item_id": proposed_item_id,
            "reason": reason,
            "status": "PROPOSED",
        }
    )
    db.substitution_requests[sub["id"]] = sub
    return success_object(ser_substitution_request(sub), 201)


@bp.get("/substitution-requests")
@require_roles(*ROLES)
def list_substitution_requests():
    quote_line_id = _query_arg("quote_line_id")
    proposed_item_id = _query_arg("proposed_item_id")
    status = _query_arg("status")
    items = sorted(db.substitution_requests.values(), key=sort_key)
    if quote_line_id is not None:
        items = [s for s in items if s["quote_line_id"] == quote_line_id]
    if proposed_item_id is not None:
        items = [s for s in items if s["proposed_item_id"] == proposed_item_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([ser_substitution_request(s) for s in page], limit, offset, total)


@bp.get("/substitution-requests/<sub_id>")
@require_roles(*ROLES)
def get_substitution_request(sub_id: str):
    sub = db.substitution_requests.get(sub_id)
    if sub is None:
        raise_err(ERR_SUBSTITUTION_REQUEST_NOT_FOUND, "No substitution request with the given id")
    return success_object(ser_substitution_request(sub))


@bp.post("/substitution-requests/<sub_id>/decide")
@require_roles("BranchManager")
@atomic
def decide_substitution_request(sub_id: str):
    body = get_json_body()
    decision = require_string(body, "decision")
    if decision not in ("APPROVE", "REJECT"):
        raise_err(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT")

    sub = db.substitution_requests.get(sub_id)
    if sub is None:
        raise_err(ERR_SUBSTITUTION_REQUEST_NOT_FOUND, "No substitution request with the given id")
    if sub["status"] != "PROPOSED":
        raise_err(ERR_SUBSTITUTION_NOT_PROPOSED, "Decide requires the substitution request in PROPOSED")

    line = db.quote_lines[sub["quote_line_id"]]
    quote = db.quotes[line["quote_id"]]
    if quote["status"] != "DRAFT":
        raise_err(ERR_QUOTE_NOT_DRAFT, "Decide requires the owning quote in DRAFT")

    sub["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    touch(sub)
    if decision == "APPROVE":
        line["catalog_item_id"] = sub["proposed_item_id"]
        touch(line)
    return success_object(ser_substitution_request(sub))
