"""Member endpoints."""

from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list, parse_iso_date,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_REFERENCE_MISMATCH,
    ERR_CHILD_MUST_HAVE_GUARDIAN,
)

bp = Blueprint("members", __name__)

MEMBER_TYPES = {"ADULT", "CHILD"}
MEMBERSHIP_STATUSES = {"VISITOR", "REGULAR", "MEMBER", "DEPARTED"}


def _validate_member_body_common(body, is_create):
    if is_create:
        # household_id, full_name, date_of_birth, member_type required
        for k in ("household_id", "full_name", "date_of_birth", "member_type"):
            if k not in body or body[k] is None:
                raise_err(ERR_INVALID_REQUEST, f"{k} is required")

    if "full_name" in body:
        if not isinstance(body["full_name"], str) or body["full_name"] == "":
            raise_err(ERR_INVALID_REQUEST, "full_name must be a non-empty string")
    if "date_of_birth" in body:
        try:
            parse_iso_date(body["date_of_birth"])
        except Exception:
            raise_err(ERR_INVALID_REQUEST, "date_of_birth must be YYYY-MM-DD")
    if "member_type" in body:
        if body["member_type"] not in MEMBER_TYPES:
            raise_err(ERR_INVALID_REQUEST, "member_type must be ADULT or CHILD")
    if "membership_status" in body:
        if body["membership_status"] not in MEMBERSHIP_STATUSES:
            raise_err(ERR_INVALID_REQUEST, "membership_status invalid")
    if "email" in body and body["email"] is not None:
        if not isinstance(body["email"], str):
            raise_err(ERR_INVALID_REQUEST, "email must be string or null")
    if "phone" in body and body["phone"] is not None:
        if not isinstance(body["phone"], str):
            raise_err(ERR_INVALID_REQUEST, "phone must be string or null")
    if "allow_directory_publish" in body:
        if not isinstance(body["allow_directory_publish"], bool):
            raise_err(ERR_INVALID_REQUEST, "allow_directory_publish must be a boolean")
    if "guardian_member_ids" in body and body["guardian_member_ids"] is not None:
        gm = body["guardian_member_ids"]
        if not isinstance(gm, list) or not all(isinstance(x, str) for x in gm):
            raise_err(ERR_INVALID_REQUEST, "guardian_member_ids must be a list of strings")


@bp.route("/members", methods=["POST"])
def create_member():
    require_role({"Registrar", "PlatformAdmin"})
    body = get_json_body()
    _validate_member_body_common(body, is_create=True)

    hid = body["household_id"]
    household = db.households.get(hid)
    if household is None:
        raise_err(ERR_NOT_FOUND, "household_id not found")

    mtype = body["member_type"]
    guardians = list(body.get("guardian_member_ids") or [])

    if mtype == "CHILD":
        if not guardians:
            raise_err(ERR_CHILD_MUST_HAVE_GUARDIAN, "CHILD requires guardian_member_ids")
        # All guardian ids must exist, be ADULT, and in same household.
        for gid in guardians:
            gm = db.members.get(gid)
            if gm is None:
                # Priority 3 existence check for referenced ids in the body.
                raise_err(ERR_NOT_FOUND, f"guardian {gid} not found")
        # Priority 13 ref check — must be ADULT + same household.
        for gid in guardians:
            gm = db.members[gid]
            if gm.get("member_type") != "ADULT" or gm.get("household_id") != hid:
                raise_err(ERR_CHILD_MUST_HAVE_GUARDIAN,
                          "each guardian must be an ADULT in the same household")
        email = body.get("email")
    else:
        # ADULT — email required per PRD §3.1.
        email = body.get("email")
        if email is None or (isinstance(email, str) and email == ""):
            raise_err(ERR_INVALID_REQUEST, "email is required for ADULT members")
        guardians = []

    rec = {
        "household_id": hid,
        "full_name": body["full_name"],
        "date_of_birth": body["date_of_birth"],
        "member_type": mtype,
        "guardian_member_ids": guardians,
        "email": email,
        "phone": body.get("phone"),
        "membership_status": "VISITOR",
        "allow_directory_publish": (
            body["allow_directory_publish"] if "allow_directory_publish" in body else True
        ),
    }
    stamp_common_create(rec)
    db.members[rec["id"]] = rec
    return success(rec, 201)


@bp.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    require_role({"Registrar", "Coordinator", "FinanceAdmin", "Member", "PlatformAdmin"})
    rec = must_exist(db.members, mid, "Member")
    return success(rec, 200)


@bp.route("/members/<mid>", methods=["PATCH"])
def patch_member(mid):
    require_role({"Registrar", "PlatformAdmin"})
    rec = must_exist(db.members, mid, "Member")
    body = get_json_body()
    _validate_member_body_common(body, is_create=False)

    changed = False
    for k in ("full_name", "email", "phone", "membership_status", "allow_directory_publish"):
        if k in body:
            rec[k] = body[k]
            changed = True

    if changed:
        bump(rec)
    return success(rec, 200)
