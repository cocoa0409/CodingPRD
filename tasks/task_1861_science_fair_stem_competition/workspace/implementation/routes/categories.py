"""Category routes."""

from flask import Blueprint, request
import db
import validators as V
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination, paginate
from serializers import category_out
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_ADVANCEMENT_FROZEN, ERR_STALE_VERSION, ERR_REFERENTIAL_INTEGRITY,
)

bp = Blueprint("categories", __name__)

_ALL_ROLES = ("FairDirector", "Mentor", "EthicsReviewer", "Judge",
              "OperationsLead", "SafetyInspector")

_VALID_GRADE_BAND = {"JUNIOR", "SENIOR"}
_VALID_STATUS = {"OPEN", "LOCKED"}
_PATCHABLE_PHASES = {"SETUP", "REGISTRATION_OPEN", "REGISTRATION_CLOSED",
                     "JUDGING"}


def _touch(c):
    c["updated_at"] = db.now_display_iso()
    c["version"] += 1


@bp.route("/science-fair/categories", methods=["POST"])
def create_category():
    body = V.get_json_body()
    V.require_fields(body, ["fair_edition_id", "code", "name", "grade_band",
                            "advancement_slots"])
    feid = V.req_str(body, "fair_edition_id")
    code = V.req_str(body, "code")
    name = V.req_str(body, "name")
    grade_band = V.req_enum(body, "grade_band", _VALID_GRADE_BAND)
    slots = V.req_int(body, "advancement_slots")
    if slots < 0:
        raise_err(ERR_INVALID_REQUEST,
                  "advancement_slots must be >= 0")

    require_roles("FairDirector")

    # Referential integrity: edition must exist
    edition = db.fair_editions.get(feid)
    if edition is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  f"Fair edition not found: {feid}")

    now = db.now_display_iso()
    c = {
        "id": db.new_id(),
        "fair_edition_id": feid,
        "code": code,
        "name": name,
        "grade_band": grade_band,
        "advancement_slots": slots,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.categories[c["id"]] = c
    return success_object(category_out(c), 201)


@bp.route("/science-fair/categories", methods=["GET"])
def list_categories():
    require_roles(*_ALL_ROLES)
    limit, offset = parse_pagination()
    feid = request.args.get("fair_edition_id")
    items = list(db.categories.values())
    if feid:
        items = [c for c in items if c["fair_edition_id"] == feid]
    data, total = paginate(items, category_out, limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/categories/<cid>", methods=["GET"])
def get_category(cid):
    require_roles(*_ALL_ROLES)
    c = db.categories.get(cid)
    if c is None:
        raise_err(ERR_NOT_FOUND, f"Category not found: {cid}")
    return success_object(category_out(c))


@bp.route("/science-fair/categories/<cid>", methods=["PATCH"])
def patch_category(cid):
    body = V.get_json_body()
    V.require_fields(body, ["expected_fair_edition_version"])
    expected = V.req_int(body, "expected_fair_edition_version")
    name = V.opt_str(body, "name")
    slots = V.opt_int(body, "advancement_slots")
    if slots is not None and slots < 0:
        raise_err(ERR_INVALID_REQUEST,
                  "advancement_slots must be >= 0")

    require_roles("FairDirector")

    c = db.categories.get(cid)
    if c is None:
        raise_err(ERR_NOT_FOUND, f"Category not found: {cid}")

    edition = db.fair_editions.get(c["fair_edition_id"])
    if edition is None:
        raise_err(ERR_REFERENTIAL_INTEGRITY,
                  f"Parent fair edition missing: {c['fair_edition_id']}")

    # Phase gate: freeze => ERR_ADVANCEMENT_FROZEN; ARCHIVED handled by
    # terminal guard on edition phase (advancement_freeze stays true, so the
    # freeze error covers post-publication). Allowed phases listed in PRD.
    if edition["advancement_freeze"]:
        raise_err(ERR_ADVANCEMENT_FROZEN,
                  "Category quota edit attempted after advancement_freeze")
    if edition["status"] not in _PATCHABLE_PHASES:
        raise_err(ERR_INVALID_STATE,
                  f"Category edit not allowed while edition is "
                  f"{edition['status']}")

    # OCC against parent edition
    if expected != edition["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_fair_edition_version does not match current "
                  "edition version")

    if name is not None:
        c["name"] = name
    if slots is not None:
        c["advancement_slots"] = slots
    _touch(c)
    # Successful update bumps the parent edition version too
    edition["updated_at"] = db.now_display_iso()
    edition["version"] += 1

    return success_object(category_out(c))
