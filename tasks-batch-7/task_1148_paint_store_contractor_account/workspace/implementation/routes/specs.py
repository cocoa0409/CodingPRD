"""Specification sheets and spec lines (architect specs + pull-through)."""
from flask import Blueprint, request

import db
import services as svc
from authz import require_roles
from envelope import ok_object, ok_list
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_VALIDATION,
    ERR_INVALID_STATE, ERR_SPEC_NOT_REVIEWABLE, ERR_SPEC_NOT_REVISABLE,
    ERR_SPEC_EMPTY, ERR_PRODUCT_DISCONTINUED,
)
from serializers import ser_spec_sheet, ser_spec_line, sorted_rows
from validate import body_json, req_str, pagination_params, query_enum_filter

bp = Blueprint("specs", __name__)

WRITER = ["SpecWriter"]
ADMIN = ["CorporateAdmin"]
ALL_READERS = ["CorporateAdmin", "StoreManager", "StoreAssociate", "SpecWriter", "Contractor"]
SHEET_STATUS = {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "NEEDS_REVISION", "SUPERSEDED"}


def _get_sheet(sheet_id):
    s = db.spec_sheets.get(sheet_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, "spec sheet %s not found" % sheet_id)
    return s


def _parse_lines(data):
    """Body references first (stage 5), then shape (stage 6). Returns parsed lines."""
    raw = data.get("lines")
    if isinstance(raw, list):
        for li in raw:
            if not isinstance(li, dict):
                continue
            pid = li.get("product_id")
            if isinstance(pid, str) and pid not in db.products:
                raise_err(ERR_REFERENCE_NOT_FOUND, "product_id %s not found" % pid)
    if not isinstance(raw, list):
        raise_err(ERR_VALIDATION, "field 'lines' is required and must be an array")
    parsed = []
    for i, li in enumerate(raw):
        if not isinstance(li, dict):
            raise_err(ERR_VALIDATION, "field 'lines[%d]' must be an object" % i)
        pid = li.get("product_id")
        if not isinstance(pid, str):
            raise_err(ERR_VALIDATION, "field 'lines[%d].product_id' is required" % i)
        qty = li.get("specified_qty")
        if not isinstance(qty, int) or isinstance(qty, bool):
            raise_err(ERR_VALIDATION, "field 'lines[%d].specified_qty' must be an integer" % i)
        if qty <= 0:
            raise_err(ERR_VALIDATION, "field 'lines[%d].specified_qty' must be > 0" % i)
        parsed.append({"product_id": pid, "specified_qty": qty})
    return parsed


def _create_lines(sheet_id, parsed):
    for pl in parsed:
        line = svc.stamp_new({
            "spec_sheet_id": sheet_id,
            "product_id": pl["product_id"],
            "specified_qty": pl["specified_qty"],
            "obsoleted": False,
        })
        db.spec_lines[line["id"]] = line


@bp.post("/spec-sheets")
def create_sheet():
    require_roles(WRITER)
    data = body_json()
    parsed = _parse_lines(data)
    project_code = req_str(data, "project_code")
    architect_name = req_str(data, "architect_name")
    title = req_str(data, "title")
    sheet = svc.stamp_new({
        "project_code": project_code,
        "architect_name": architect_name,
        "title": title,
        "status": "DRAFT",
        "rejection_reason": None,
        "approved_at": None,
        "supersedes_spec_sheet_id": None,
    })
    db.spec_sheets[sheet["id"]] = sheet
    _create_lines(sheet["id"], parsed)
    return ok_object(ser_spec_sheet(sheet), 201)


@bp.get("/spec-sheets/<sheet_id>")
def get_sheet(sheet_id):
    require_roles(ALL_READERS)
    return ok_object(ser_spec_sheet(_get_sheet(sheet_id)))


@bp.get("/spec-sheets")
def list_sheets():
    require_roles(ALL_READERS)
    limit, offset = pagination_params()
    status_filter = query_enum_filter("status", SHEET_STATUS)
    project_filter = request.args.get("project_code")
    supersedes_filter = request.args.get("supersedes_spec_sheet_id")
    rows = list(db.spec_sheets.values())
    if status_filter is not None:
        rows = [s for s in rows if s["status"] == status_filter]
    if project_filter is not None:
        rows = [s for s in rows if s["project_code"] == project_filter]
    if supersedes_filter is not None:
        rows = [s for s in rows if s["supersedes_spec_sheet_id"] == supersedes_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_spec_sheet(s) for s in rows[offset:offset + limit]], total, limit, offset)


@bp.post("/spec-sheets/<sheet_id>/submit")
def submit_sheet(sheet_id):
    require_roles(WRITER)
    sheet = _get_sheet(sheet_id)
    if sheet["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "spec sheet is not DRAFT")
    if not svc.sheet_lines(sheet_id):
        raise_err(ERR_SPEC_EMPTY, "spec sheet has no lines")
    sheet["status"] = "SUBMITTED"
    svc.bump(sheet)
    return ok_object(ser_spec_sheet(sheet))


@bp.post("/spec-sheets/<sheet_id>/approve")
def approve_sheet(sheet_id):
    require_roles(ADMIN)
    sheet = _get_sheet(sheet_id)
    if sheet["status"] != "SUBMITTED":
        raise_err(ERR_SPEC_NOT_REVIEWABLE, "spec sheet is not SUBMITTED")
    # Version-pinning gate: every line's product must still be ACTIVE.
    for line in svc.sheet_lines(sheet_id):
        product = db.products.get(line["product_id"])
        if product is None or product["status"] != "ACTIVE":
            raise_err(ERR_PRODUCT_DISCONTINUED,
                      "spec line references a DISCONTINUED product")
    # Single approval per project_code: any OTHER APPROVED sheet is superseded.
    prior = None
    for other in db.spec_sheets.values():
        if other["id"] != sheet_id and other["project_code"] == sheet["project_code"] \
                and other["status"] == "APPROVED":
            prior = other
            break
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        svc.bump(prior)
    sheet["status"] = "APPROVED"
    sheet["approved_at"] = db.now()
    sheet["supersedes_spec_sheet_id"] = prior["id"] if prior is not None else None
    svc.bump(sheet)
    return ok_object(ser_spec_sheet(sheet))


@bp.post("/spec-sheets/<sheet_id>/reject")
def reject_sheet(sheet_id):
    require_roles(ADMIN)
    sheet = _get_sheet(sheet_id)
    data = body_json()
    reason = req_str(data, "reason")
    if sheet["status"] != "SUBMITTED":
        raise_err(ERR_SPEC_NOT_REVIEWABLE, "spec sheet is not SUBMITTED")
    sheet["status"] = "REJECTED"
    sheet["rejection_reason"] = reason
    svc.bump(sheet)
    return ok_object(ser_spec_sheet(sheet))


@bp.post("/spec-sheets/<sheet_id>/revise")
def revise_sheet(sheet_id):
    require_roles(WRITER)
    sheet = _get_sheet(sheet_id)
    data = body_json()
    parsed = _parse_lines(data)
    if sheet["status"] not in {"REJECTED", "NEEDS_REVISION"}:
        raise_err(ERR_SPEC_NOT_REVISABLE, "spec sheet is not REJECTED or NEEDS_REVISION")
    # Atomic line-set replacement: old lines deleted, new ones created.
    for line in svc.sheet_lines(sheet_id):
        del db.spec_lines[line["id"]]
    _create_lines(sheet_id, parsed)
    if sheet["status"] == "REJECTED":
        sheet["rejection_reason"] = None
    sheet["status"] = "DRAFT"
    svc.bump(sheet)
    return ok_object(ser_spec_sheet(sheet))


# --- spec lines ---------------------------------------------------------------------
@bp.get("/spec-lines")
def list_spec_lines():
    require_roles(ALL_READERS)
    limit, offset = pagination_params()
    sheet_filter = request.args.get("spec_sheet_id")
    product_filter = request.args.get("product_id")
    rows = list(db.spec_lines.values())
    if sheet_filter is not None:
        rows = [l for l in rows if l["spec_sheet_id"] == sheet_filter]
    if product_filter is not None:
        rows = [l for l in rows if l["product_id"] == product_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_spec_line(l) for l in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/spec-lines/<line_id>")
def get_spec_line(line_id):
    require_roles(ALL_READERS)
    line = db.spec_lines.get(line_id)
    if line is None:
        raise_err(ERR_NOT_FOUND, "spec line %s not found" % line_id)
    return ok_object(ser_spec_line(line))
