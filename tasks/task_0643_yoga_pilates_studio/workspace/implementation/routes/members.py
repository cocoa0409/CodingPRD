"""Member endpoints + member-scoped relationship reads."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import authenticate, require_roles
from models import make_member, serialize
from response import success, list_success
from helpers import (get_json_body, parse_pagination, paginate,
                     require_str, find_or_404)

bp = Blueprint("members", __name__)


def _owns_member(principal, member_id):
    """Member may only act on their own member-scoped resource."""
    if principal.is_manager:
        return True
    if principal.is_member:
        return principal.user_id == member_id
    return False


@bp.post("/members")
def create_member():
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    home_studio_state = require_str(body, "home_studio_state")
    # email unique across members
    for m in store.members.values():
        if m["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email already in use")
    member = make_member(email, full_name, home_studio_state)
    store.members[member["id"]] = member
    return success(serialize(member), status=201)


@bp.get("/members/<mid>")
def get_member(mid):
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    member = find_or_404(store.members, mid, "Member")
    if principal.is_member and principal.user_id != mid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only fetch their own record")
    return success(serialize(member))


@bp.get("/members")
def list_members():
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    limit, offset = parse_pagination()
    email = request.args.get("email")
    account_status = request.args.get("account_status")
    items = list(store.members.values())
    if email is not None:
        items = [m for m in items if m["email"] == email]
    if account_status is not None:
        items = [m for m in items if m["account_status"] == account_status]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(m) for m in window], 200, limit, offset, total)


def _member_scoped_list(mid, principal, collection_getter, fk, filters):
    member = find_or_404(store.members, mid, "Member")
    if principal.is_member and principal.user_id != mid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only list their own resources")
    limit, offset = parse_pagination()
    items = [r for r in collection_getter() if r[fk] == mid]
    for key, val in filters.items():
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    window, total = paginate(items, limit, offset)
    return window, limit, offset, total


@bp.get("/members/<mid>/reservations")
def member_reservations(mid):
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    window, limit, offset, total = _member_scoped_list(
        mid, principal, lambda: store.reservations.values(), "member_id",
        {"status": request.args.get("status")})
    return list_success([serialize(r) for r in window], 200, limit, offset, total)


@bp.get("/members/<mid>/entitlements")
def member_entitlements(mid):
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    window, limit, offset, total = _member_scoped_list(
        mid, principal, lambda: store.entitlements.values(), "member_id",
        {"kind": request.args.get("kind"),
         "lifecycle_status": request.args.get("lifecycle_status")})
    return list_success([serialize(r) for r in window], 200, limit, offset, total)


@bp.get("/members/<mid>/fee-charges")
def member_fee_charges(mid):
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    window, limit, offset, total = _member_scoped_list(
        mid, principal, lambda: store.fee_charges.values(), "member_id",
        {"status": request.args.get("status")})
    return list_success([serialize(r) for r in window], 200, limit, offset, total)


@bp.get("/members/<mid>/enrollments")
def member_enrollments(mid):
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    window, limit, offset, total = _member_scoped_list(
        mid, principal, lambda: store.enrollments.values(), "member_id",
        {"status": request.args.get("status")})
    return list_success([serialize(r) for r in window], 200, limit, offset, total)
