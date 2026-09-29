"""Standards and success criteria (PRD 3.1)."""
import re

from flask import Blueprint

from db import db, new_row, sort_key
from errors import ApiError, bad_request
from middleware import ALL_ROLES, endpoint
from response import list_response, obj_response
from serialize import criterion_out, standard_out
from validate import (
    DISABILITY_CATEGORIES,
    LEVELS,
    LEVEL_RANK,
    STANDARD_CODES,
    SURFACES,
    SURFACE_SCOPES,
    body,
    pagination,
    paginate,
    path_criterion,
    path_standard,
    q_enum,
    v_enum,
    v_enum_array,
    v_str,
)

bp = Blueprint("standards", __name__)

_NUMBER_RE = re.compile(r"^[0-9]+(\.[0-9]+){1,2}$")


@bp.post("/standards")
@endpoint(["AccessibilityLead"])
def create_standard():
    data = body()
    code = v_enum(data, "code", STANDARD_CODES, required=True)
    title = v_str(data, "title", required=True, min_len=1, max_len=200)
    surface_scope = v_enum(data, "surface_scope", SURFACE_SCOPES, required=True)
    max_target_level = v_enum(data, "max_target_level", LEVELS, required=True)

    # step 35: uniqueness
    for existing in db.standards.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_STANDARD_CODE",
                           "Standard code %s is already registered" % code)

    row = new_row({
        "code": code,
        "title": title,
        "surface_scope": surface_scope,
        "max_target_level": max_target_level,
    })
    db.standards[row["id"]] = row
    return obj_response(standard_out(row), 201)


@bp.get("/standards/<standard_id>")
@endpoint(ALL_ROLES)
def get_standard(standard_id):
    return obj_response(standard_out(path_standard(standard_id)))


@bp.post("/standards/<standard_id>/criteria")
@endpoint(["AccessibilityLead"])
def create_criterion(standard_id):
    standard = path_standard(standard_id)
    data = body()
    number = v_str(data, "criterion_number", required=True, min_len=1, max_len=40)
    if not _NUMBER_RE.match(number):
        raise bad_request("'criterion_number' must be dotted decimal groups")
    title = v_str(data, "title", required=True, min_len=1, max_len=200)
    level = v_enum(data, "level", LEVELS, required=True)
    categories = v_enum_array(data, "disability_categories", DISABILITY_CATEGORIES,
                              required=True)
    surfaces = v_enum_array(data, "applies_to_surfaces", SURFACES, required=True)

    # step 35: uniqueness within the standard
    for existing in db.criteria.values():
        if (existing["standard_id"] == standard["id"]
                and existing["criterion_number"] == number):
            raise ApiError("ERR_DUPLICATE_CRITERION_NUMBER",
                           "Criterion %s already exists on this standard" % number)

    # step 37: level compatibility
    if LEVEL_RANK[level] > LEVEL_RANK[standard["max_target_level"]]:
        raise ApiError("ERR_LEVEL_OR_SURFACE_UNSUPPORTED",
                       "Level %s exceeds the standard's maximum target level %s"
                       % (level, standard["max_target_level"]))

    row = new_row({
        "standard_id": standard["id"],
        "criterion_number": number,
        "title": title,
        "level": level,
        "disability_categories": categories,
        "applies_to_surfaces": surfaces,
    }, versioned=False)
    db.criteria[row["id"]] = row
    return obj_response(criterion_out(row), 201)


@bp.get("/standards/<standard_id>/criteria")
@endpoint(ALL_ROLES)
def list_criteria(standard_id):
    standard = path_standard(standard_id)
    level = q_enum("level", LEVELS)
    limit, offset = pagination()
    rows = [c for c in db.criteria.values() if c["standard_id"] == standard["id"]]
    if level is not None:
        rows = [c for c in rows if c["level"] == level]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return list_response([criterion_out(r) for r in page], limit, offset, total)


@bp.get("/criteria/<criterion_id>")
@endpoint(ALL_ROLES)
def get_criterion(criterion_id):
    return obj_response(criterion_out(path_criterion(criterion_id)))
