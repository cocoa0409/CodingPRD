"""Org units (PRD §3.2)."""

from flask import Blueprint, request

from db import db, stamp_new, touch, public
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND,
    ERR_UNIT_CYCLE, ERR_THRESHOLD_INVERSION,
)
from middleware import (
    require_roles, parse_pagination, paginate, get_json_body,
    require_fields, optional_fields_present, as_non_empty_string, as_int,
    as_string,
)
from response import success_object, success_list
from services.domain import would_create_unit_cycle

bp = Blueprint("org_units", __name__)


def _get_unit_or_404(unit_id):
    unit = db.org_units.get(unit_id)
    if unit is None:
        raise err(ERR_NOT_FOUND, "org unit not found", 404)
    return unit


def _validate_thresholds(min_n, verbatim_n):
    """min_n in 3..20; verbatim_n >= min_n."""
    if min_n is not None and (min_n < 3 or min_n > 20):
        raise err(ERR_VALIDATION, "min_n_threshold must be between 3 and 20", 400)
    if verbatim_n is not None and min_n is not None and verbatim_n < min_n:
        raise err(ERR_THRESHOLD_INVERSION,
                  "verbatim_n_threshold must be >= min_n_threshold", 422)


@bp.post("/engagement/org-units")
def create_org_unit():
    require_roles("HRAdmin")
    body = get_json_body()
    optional_fields_present(body, {
        "name", "manager_user_id", "parent_unit_id",
        "min_n_threshold", "verbatim_n_threshold",
    })
    require_fields(body, ["name", "manager_user_id"])
    name = as_non_empty_string(body["name"], "name")
    manager_user_id = as_non_empty_string(body["manager_user_id"], "manager_user_id")

    parent_unit_id = body.get("parent_unit_id")
    if parent_unit_id is not None:
        as_non_empty_string(parent_unit_id, "parent_unit_id")
        if parent_unit_id not in db.org_units:
            raise err(ERR_REFERENCE_NOT_FOUND, "parent_unit_id does not exist", 404)

    min_n = body.get("min_n_threshold")
    if min_n is not None:
        min_n = as_int(min_n, "min_n_threshold")
    verbatim_n = body.get("verbatim_n_threshold")
    if verbatim_n is not None:
        verbatim_n = as_int(verbatim_n, "verbatim_n_threshold")

    eff_min_n = 5 if min_n is None else min_n
    eff_verbatim_n = 10 if verbatim_n is None else verbatim_n
    if eff_min_n < 3 or eff_min_n > 20:
        raise err(ERR_VALIDATION, "min_n_threshold must be between 3 and 20", 400)
    if eff_verbatim_n < eff_min_n:
        raise err(ERR_THRESHOLD_INVERSION,
                  "verbatim_n_threshold must be >= min_n_threshold", 422)

    # Acyclicity: a fresh node cannot close a cycle (it has no children yet),
    # but self-parenting is impossible here (id unknown). Guard anyway.
    if parent_unit_id is not None and parent_unit_id == "__self__":
        raise err(ERR_UNIT_CYCLE, "parent_unit_id would create a cycle", 422)

    unit = stamp_new({
        "name": name,
        "parent_unit_id": parent_unit_id,
        "manager_user_id": manager_user_id,
        "min_n_threshold": eff_min_n,
        "verbatim_n_threshold": eff_verbatim_n,
    })
    db.org_units[unit["id"]] = unit
    return success_object(public(unit), 201)


@bp.get("/engagement/org-units")
def list_org_units():
    require_roles("HRAdmin", "PeopleAnalyst", "UnitManager")
    limit, offset = parse_pagination({"parent_unit_id"})
    parent_filter = request.args.get("parent_unit_id")
    items = list(db.org_units.values())
    if parent_filter is not None:
        items = [u for u in items if u.get("parent_unit_id") == parent_filter]
    page, total = paginate(items, limit, offset)
    return success_list([public(u) for u in page], limit, offset, total)


@bp.get("/engagement/org-units/<unit_id>")
def get_org_unit(unit_id):
    require_roles("HRAdmin", "PeopleAnalyst", "UnitManager")
    unit = _get_unit_or_404(unit_id)
    return success_object(public(unit))


@bp.patch("/engagement/org-units/<unit_id>")
def update_org_unit(unit_id):
    require_roles("HRAdmin")
    unit = _get_unit_or_404(unit_id)
    body = get_json_body()
    optional_fields_present(body, {
        "parent_unit_id", "min_n_threshold", "verbatim_n_threshold",
    })

    new_parent = unit.get("parent_unit_id")
    if "parent_unit_id" in body:
        new_parent = body["parent_unit_id"]
        if new_parent is not None:
            as_non_empty_string(new_parent, "parent_unit_id")
            if new_parent not in db.org_units:
                raise err(ERR_REFERENCE_NOT_FOUND, "parent_unit_id does not exist", 404)

    new_min_n = unit["min_n_threshold"]
    if "min_n_threshold" in body and body["min_n_threshold"] is not None:
        new_min_n = as_int(body["min_n_threshold"], "min_n_threshold")
        if new_min_n < 3 or new_min_n > 20:
            raise err(ERR_VALIDATION, "min_n_threshold must be between 3 and 20", 400)

    new_verbatim_n = unit["verbatim_n_threshold"]
    if "verbatim_n_threshold" in body and body["verbatim_n_threshold"] is not None:
        new_verbatim_n = as_int(body["verbatim_n_threshold"], "verbatim_n_threshold")

    if new_verbatim_n < new_min_n:
        raise err(ERR_THRESHOLD_INVERSION,
                  "verbatim_n_threshold must be >= min_n_threshold", 422)

    if would_create_unit_cycle(unit["id"], new_parent):
        raise err(ERR_UNIT_CYCLE, "parent_unit_id would create a cycle", 422)

    unit["parent_unit_id"] = new_parent
    unit["min_n_threshold"] = new_min_n
    unit["verbatim_n_threshold"] = new_verbatim_n
    touch(unit)
    return success_object(public(unit))
