"""Family and Child endpoints."""
from __future__ import annotations

from flask import g

from flask import Blueprint

from db import db
from middleware import require_roles, current_user_id
from response import ok_object, ok_array
from common import (
    base_entity, touch, public, get_or_404, get_body,
    require_str, require_int, require_bool_optional, parse_pagination, paginate,
)
from errors import APIError, ERR_REFERENCE_NOT_FOUND, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_REQUEST
from services.pricing import compute_sliding_scale_tier

bp = Blueprint("families", __name__)


@bp.post("/families")
@require_roles("CenterDirector", "BillingAdmin")
def create_family():
    body = get_body()
    center_id = require_str(body, "center_id")
    name = require_str(body, "primary_contact_name")
    income = require_int(body, "annual_household_income_cents", minimum=0)
    size = require_int(body, "household_size", minimum=1)
    if center_id not in db.centers:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 422, "center_id does not exist")
    ent = base_entity()
    ent.update({
        "center_id": center_id,
        "primary_contact_name": name,
        "annual_household_income_cents": income,
        "household_size": size,
        "sliding_scale_tier": "FULL_PAY",
        "account_balance_cents": 0,
    })
    ent["sliding_scale_tier"] = compute_sliding_scale_tier(ent)
    db.families[ent["id"]] = ent
    return ok_object(public(ent), 201)


@bp.get("/families")
@require_roles("CenterDirector", "BillingAdmin")
def list_families():
    limit, offset = parse_pagination()
    from flask import request
    center_id = request.args.get("center_id")
    rows = list(db.families.values())
    if center_id is not None:
        rows = [r for r in rows if r["center_id"] == center_id]
    rows.sort(key=lambda r: r["_seq"])
    page, total = paginate(rows, limit, offset)
    return ok_array([public(r) for r in page], limit, offset, total, 200)


@bp.get("/families/<fid>")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def get_family(fid):
    ent = get_or_404(db.families, fid, "family")
    if g.user_role == "Parent" and current_user_id() != fid:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this family")
    return ok_object(public(ent), 200)


@bp.patch("/families/<fid>")
@require_roles("CenterDirector", "BillingAdmin")
def update_family(fid):
    ent = get_or_404(db.families, fid, "family")
    body = get_body()
    changed = False
    if "annual_household_income_cents" in body and body["annual_household_income_cents"] is not None:
        ent["annual_household_income_cents"] = require_int(body, "annual_household_income_cents", minimum=0)
        changed = True
    if "household_size" in body and body["household_size"] is not None:
        ent["household_size"] = require_int(body, "household_size", minimum=1)
        changed = True
    if changed:
        ent["sliding_scale_tier"] = compute_sliding_scale_tier(ent)
        touch(ent)
    return ok_object(public(ent), 200)


@bp.post("/children")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def create_child():
    body = get_body()
    family_id = require_str(body, "family_id")
    full_name = require_str(body, "full_name")
    birthdate = require_str(body, "birthdate")
    if family_id not in db.families:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 422, "family_id does not exist")
    # ownership: Parent may only register for their own family
    if g.user_role == "Parent" and current_user_id() != family_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this family")
    enrolls = require_bool_optional(body, "enrolls_in_cacfp", True)
    sibling_group_id = body.get("sibling_group_id")
    if sibling_group_id is not None and not isinstance(sibling_group_id, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "sibling_group_id must be a string")
    if sibling_group_id is not None and sibling_group_id not in db.children:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 422, "sibling_group_id does not exist")
    ent = base_entity()
    ent.update({
        "family_id": family_id,
        "full_name": full_name,
        "birthdate": birthdate,
        "sibling_group_id": sibling_group_id if sibling_group_id is not None else ent["id"],
        "enrolls_in_cacfp": enrolls,
    })
    db.children[ent["id"]] = ent
    return ok_object(public(ent), 201)


@bp.get("/children")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def list_children():
    from flask import request
    limit, offset = parse_pagination()
    family_id = request.args.get("family_id")
    sibling_group_id = request.args.get("sibling_group_id")
    rows = list(db.children.values())
    if family_id is not None:
        rows = [r for r in rows if r["family_id"] == family_id]
    if sibling_group_id is not None:
        rows = [r for r in rows if r["sibling_group_id"] == sibling_group_id]
    if g.user_role == "Parent":
        rows = [r for r in rows if r["family_id"] == current_user_id()]
    rows.sort(key=lambda r: r["_seq"])
    page, total = paginate(rows, limit, offset)
    return ok_array([public(r) for r in page], limit, offset, total, 200)


@bp.get("/children/<rid>")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def get_child(rid):
    ent = get_or_404(db.children, rid, "child")
    if g.user_role == "Parent" and current_user_id() != ent["family_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this child")
    return ok_object(public(ent), 200)
