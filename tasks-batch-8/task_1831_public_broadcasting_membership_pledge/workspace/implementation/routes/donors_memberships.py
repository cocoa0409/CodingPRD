"""Donors and memberships."""

from flask import Blueprint, request

import db
import response
import validators as v
from errors import ApiError, ERR_DUPLICATE_CODE, ERR_INVALID_STATE, ERR_NOT_FOUND
from middleware import require_roles
from services import core

bp = Blueprint("donors_memberships", __name__)

ALL_ROLES = ("StationAdmin", "MembershipCoordinator", "PhoneVolunteer")


# --- Donors ---

@bp.route("/station/donors", methods=["POST"])
def create_donor():
    body = v.get_json_body()
    require_roles("MembershipCoordinator", "PhoneVolunteer")
    email = v.req_str(body, "email")
    full_name = v.req_str(body, "full_name")
    postal_code = v.req_str(body, "postal_code")

    key = email.lower()
    if key in db.donors_by_email:
        raise ApiError(ERR_DUPLICATE_CODE[0], f"Donor email '{email}' already exists", ERR_DUPLICATE_CODE[1])

    ent = db.new_entity()
    ent.update({
        "email": email,
        "full_name": full_name,
        "postal_code": postal_code,
        "lifetime_given_cents": 0,
        "lapse_count": 0,
    })
    db.donors[ent["id"]] = ent
    db.donors_by_email[key] = ent["id"]
    return response.success_object(ent, status=201)


@bp.route("/station/donors/<did>", methods=["GET"])
def get_donor(did):
    require_roles(*ALL_ROLES)
    ent = db.donors.get(did)
    if ent is None:
        v.not_found(f"Donor '{did}' not found")
    return response.success_object(ent)


@bp.route("/station/donors/<did>/memberships", methods=["GET"])
def list_donor_memberships(did):
    require_roles(*ALL_ROLES)
    if did not in db.donors:
        v.not_found(f"Donor '{did}' not found")
    limit, offset = v.parse_pagination(request.args)
    items = [m for m in db.memberships.values() if m["donor_id"] == did]
    items = v.sort_created(items)
    page, total = v.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


# --- Memberships ---

@bp.route("/station/memberships", methods=["POST"])
def create_membership():
    body = v.get_json_body()
    require_roles("MembershipCoordinator", "PhoneVolunteer")
    donor_id = v.req_str(body, "donor_id")
    level_code = v.req_str(body, "level_code")
    sustainer = v.opt_bool(body, "sustainer", default=False)

    donor = db.donors.get(donor_id)
    if donor is None:
        v.not_found(f"Donor '{donor_id}' not found")
    level = core.get_level_by_code(level_code)
    if level is None:
        raise ApiError(ERR_NOT_FOUND[0], f"MembershipLevel '{level_code}' not found", ERR_NOT_FOUND[1])

    now_iso = db.iso(db.now())
    ent = db.new_entity()
    ent.update({
        "donor_id": donor_id,
        "level_code": level_code,
        "status": "ACTIVE",
        "current_period_start": now_iso,
        "current_period_end": now_iso,
        "sustainer": sustainer,
    })
    db.memberships[ent["id"]] = ent
    return response.success_object(ent, status=201)


@bp.route("/station/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    require_roles(*ALL_ROLES)
    ent = db.memberships.get(mid)
    if ent is None:
        v.not_found(f"Membership '{mid}' not found")
    return response.success_object(ent)


@bp.route("/station/memberships/<mid>/reinstate", methods=["POST"])
def reinstate_membership(mid):
    v.get_json_body(required=False)
    require_roles("MembershipCoordinator")
    ent = db.memberships.get(mid)
    if ent is None:
        v.not_found(f"Membership '{mid}' not found")
    if ent["status"] != "LAPSED":
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Membership must be LAPSED to reinstate (current: {ent['status']})",
                       ERR_INVALID_STATE[1])
    ent["status"] = "REINSTATED_PENDING"
    db.touch(ent)
    return response.success_object(ent)


@bp.route("/station/memberships", methods=["GET"])
def list_memberships():
    require_roles("StationAdmin", "MembershipCoordinator")
    limit, offset = v.parse_pagination(request.args)
    items = list(db.memberships.values())
    status_q = request.args.get("status")
    if status_q is not None:
        items = [m for m in items if m["status"] == status_q]
    donor_q = request.args.get("donor_id")
    if donor_q is not None:
        items = [m for m in items if m["donor_id"] == donor_q]
    sustainer_q = request.args.get("sustainer")
    if sustainer_q is not None:
        if sustainer_q.lower() == "true":
            items = [m for m in items if m["sustainer"]]
        elif sustainer_q.lower() == "false":
            items = [m for m in items if not m["sustainer"]]
        else:
            v.invalid("Query parameter 'sustainer' must be 'true' or 'false'")
    items = v.sort_created(items)
    page, total = v.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)
