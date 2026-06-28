"""AuthorizedRepresentative routes."""
from datetime import date

from flask import Blueprint, request

from db import db, stamp_new, touch
from middleware import get_identity, require_role
from response import ok, created, ok_list
from errors import err
from services import domain
from routes.common import (
    get_body, find_or_404, require_string, require_enum, paginate,
    check_account_owner,
)

bp = Blueprint("representatives", __name__)

ALL_ROLES = {"ProgramAdministrator", "Beneficiary", "AuthorizedRepresentative"}
RELATIONSHIPS = {"PARENT", "GUARDIAN", "POA_AGENT", "SPOUSE"}


def _parse_date(s):
    return date.fromisoformat(str(s)[:10])


@bp.post("/able/accounts/<aid>/authorized-representatives")
def create_representative(aid):
    user_id, role = get_identity()
    require_role(role, {"ProgramAdministrator", "Beneficiary"})
    a = find_or_404(db.accounts, aid, "Account")
    # ownership: Beneficiary must own the account (priority 4)
    if role == "Beneficiary":
        check_account_owner(a, role, user_id)
    body = get_body()
    require_string(body, "full_name")
    require_enum(body, "relationship", RELATIONSHIPS)
    require_string(body, "authority_start")
    require_string(body, "authority_end")
    new_start = _parse_date(body["authority_start"])
    new_end = _parse_date(body["authority_end"])
    # representative_authority_overlap (closed) among ACTIVE reps of same relationship
    for r in db.authorized_representatives.values():
        if r["account_id"] != aid:
            continue
        if r["status"] != "ACTIVE":
            continue
        if r["relationship"] != body["relationship"]:
            continue
        r_start = _parse_date(r["authority_start"])
        r_end = _parse_date(r["authority_end"])
        # closed: overlap iff new_start <= r_end AND r_start <= new_end
        if new_start <= r_end and r_start <= new_end:
            raise err("ERR_REP_AUTHORITY_OVERLAP",
                      "Representative authority window overlaps an active representative")
    r = {
        "account_id": aid,
        "full_name": body["full_name"],
        "relationship": body["relationship"],
        "authority_start": body["authority_start"],
        "authority_end": body["authority_end"],
        "status": "ACTIVE",
    }
    stamp_new(r)
    db.authorized_representatives[r["id"]] = r
    return created(domain.serialize_representative(r))


@bp.get("/able/authorized-representatives/<rid>")
def get_representative(rid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    r = find_or_404(db.authorized_representatives, rid, "AuthorizedRepresentative")
    return ok(domain.serialize_representative(r))


@bp.get("/able/authorized-representatives")
def list_representatives():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    account_id = request.args.get("account_id")
    items = list(db.authorized_representatives.values())
    if account_id is not None:
        items = [r for r in items if r["account_id"] == account_id]
    page, limit, offset, total = paginate(items)
    return ok_list([domain.serialize_representative(r) for r in page],
                   limit, offset, total)


@bp.post("/able/authorized-representatives/<rid>/revoke")
def revoke_representative(rid):
    user_id, role = get_identity()
    require_role(role, {"ProgramAdministrator", "Beneficiary"})
    r = find_or_404(db.authorized_representatives, rid, "AuthorizedRepresentative")
    if role == "Beneficiary":
        account = db.accounts.get(r["account_id"])
        if account is None or account["beneficiary_id"] != user_id:
            raise err("ERR_NOT_ACCOUNT_OWNER", "Beneficiary does not own this account")
    if r["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Representative is not ACTIVE")
    r["status"] = "REVOKED"
    touch(r)
    return ok(domain.serialize_representative(r))
