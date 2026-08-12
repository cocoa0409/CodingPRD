"""Color-match request endpoints (counter workflow)."""
from flask import Blueprint, request

import db
import services as svc
from authz import require_roles, owner_or_forbid, scoped_account_filter
from calc import MATCH_MAX_ITERATIONS
from envelope import ok_object, ok_list
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_MATCH_NOT_REVIEWABLE, ERR_MATCH_ITERATION_EXHAUSTED,
)
from serializers import ser_match, sorted_rows
from validate import body_json, req_str, valid_shots, pagination_params, query_enum_filter

bp = Blueprint("colormatch", __name__)

MATCH_STATUS = {"SUBMITTED", "PROPOSED", "REVISION_REQUESTED", "APPROVED", "ABANDONED"}
READERS = ["CorporateAdmin", "StoreManager", "StoreAssociate", "Contractor"]


def _get_match(match_id):
    m = db.color_match_requests.get(match_id)
    if m is None:
        raise_err(ERR_NOT_FOUND, "color match request %s not found" % match_id)
    return m


@bp.post("/color-match-requests")
def create_match():
    require_roles(["StoreAssociate"])
    data = body_json()
    contractor_account_id = data.get("contractor_account_id")
    product_id = data.get("product_id")
    if isinstance(contractor_account_id, str) and contractor_account_id not in db.contractor_accounts:
        raise_err(ERR_REFERENCE_NOT_FOUND,
                  "contractor_account_id %s not found" % contractor_account_id)
    if isinstance(product_id, str) and product_id not in db.products:
        raise_err(ERR_REFERENCE_NOT_FOUND, "product_id %s not found" % product_id)
    contractor_account_id = req_str(data, "contractor_account_id")
    product_id = req_str(data, "product_id")
    sample_reference = req_str(data, "sample_reference")
    m = svc.stamp_new({
        "contractor_account_id": contractor_account_id,
        "product_id": product_id,
        "sample_reference": sample_reference,
        "status": "SUBMITTED",
        "iteration_count": 0,
        "formula_id": None,
    })
    db.color_match_requests[m["id"]] = m
    return ok_object(ser_match(m), 201)


@bp.get("/color-match-requests/<match_id>")
def get_match(match_id):
    uid, role = require_roles(READERS)
    m = _get_match(match_id)
    owner_or_forbid(uid, role, m["contractor_account_id"])
    return ok_object(ser_match(m))


@bp.get("/color-match-requests")
def list_matches():
    uid, role = require_roles(READERS)
    limit, offset = pagination_params()
    contractor_filter = scoped_account_filter(uid, role, request.args.get("contractor_account_id"))
    product_filter = request.args.get("product_id")
    formula_filter = request.args.get("formula_id")
    status_filter = query_enum_filter("status", MATCH_STATUS)
    rows = list(db.color_match_requests.values())
    if contractor_filter is not None:
        rows = [m for m in rows if m["contractor_account_id"] == contractor_filter]
    if product_filter is not None:
        rows = [m for m in rows if m["product_id"] == product_filter]
    if formula_filter is not None:
        rows = [m for m in rows if m["formula_id"] == formula_filter]
    if status_filter is not None:
        rows = [m for m in rows if m["status"] == status_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_match(m) for m in rows[offset:offset + limit]], total, limit, offset)


@bp.post("/color-match-requests/<match_id>/proposals")
def propose(match_id):
    require_roles(["StoreAssociate"])
    m = _get_match(match_id)
    data = body_json()
    color_code = req_str(data, "color_code")
    name = req_str(data, "name")
    shots = valid_shots(data)
    if m["status"] not in {"SUBMITTED", "REVISION_REQUESTED"}:
        raise_err(ERR_INVALID_STATE, "match request is not SUBMITTED or REVISION_REQUESTED")
    formula = svc.create_formula(m["product_id"], color_code, name, shots, "COLOR_MATCH")
    m["formula_id"] = formula["id"]
    m["iteration_count"] += 1
    m["status"] = "PROPOSED"
    svc.bump(m)
    return ok_object(ser_match(m), 201)


@bp.post("/color-match-requests/<match_id>/approve")
def approve(match_id):
    uid, role = require_roles(["Contractor"])
    m = _get_match(match_id)
    owner_or_forbid(uid, role, m["contractor_account_id"])
    if m["status"] != "PROPOSED":
        raise_err(ERR_MATCH_NOT_REVIEWABLE, "match request is not PROPOSED")
    m["status"] = "APPROVED"
    svc.bump(m)
    return ok_object(ser_match(m))


@bp.post("/color-match-requests/<match_id>/request-revision")
def request_revision(match_id):
    uid, role = require_roles(["Contractor"])
    m = _get_match(match_id)
    owner_or_forbid(uid, role, m["contractor_account_id"])
    # The state check fires before the iteration cap is examined.
    if m["status"] != "PROPOSED":
        raise_err(ERR_MATCH_NOT_REVIEWABLE, "match request is not PROPOSED")
    if m["iteration_count"] >= MATCH_MAX_ITERATIONS:
        raise_err(ERR_MATCH_ITERATION_EXHAUSTED,
                  "iteration cap of %d reached" % MATCH_MAX_ITERATIONS)
    formula = db.tint_formulas.get(m["formula_id"])
    if formula is not None:
        svc.retire_formula(formula)
    m["status"] = "REVISION_REQUESTED"
    svc.bump(m)
    return ok_object(ser_match(m))


@bp.post("/color-match-requests/<match_id>/abandon")
def abandon(match_id):
    uid, role = require_roles(["StoreAssociate", "Contractor"])
    m = _get_match(match_id)
    owner_or_forbid(uid, role, m["contractor_account_id"])
    if m["status"] not in {"SUBMITTED", "PROPOSED", "REVISION_REQUESTED"}:
        raise_err(ERR_INVALID_STATE,
                  "match request is not SUBMITTED, PROPOSED, or REVISION_REQUESTED")
    if m["status"] == "PROPOSED":
        formula = db.tint_formulas.get(m["formula_id"])
        if formula is not None:
            svc.retire_formula(formula)
    m["status"] = "ABANDONED"
    svc.bump(m)
    return ok_object(ser_match(m))
