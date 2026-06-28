"""Member + ConsentPatchTest routes (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from common import (bad_request, get_json_body, parse_pagination, paginate,
                    require_str, sort_by_created, stamp_create, touch)
from db import store
from lookups import (get_member_or_404, get_patch_test_or_404, get_studio_or_404,
                     ownership_member, parse_dt_or_400)
from middleware import get_user_context, require_role
from response import success_list, success_object
from services import derive
import serialize

bp = Blueprint("members", __name__)

PATCH_TEST_VALIDITY_DAYS = 365


@bp.route("/members", methods=["POST"])
def create_member():
    _, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk"})
    body = get_json_body()
    studio_id = require_str(body, "studio_id")
    studio = get_studio_or_404(studio_id)
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    # email unique within the studio.
    for m in store.members.values():
        if m["studio_id"] == studio["id"] and m["email"] == email:
            raise bad_request("email must be unique within the studio.")
    rec = {
        "studio_id": studio["id"],
        "full_name": full_name,
        "email": email,
    }
    stamp_create(rec)
    store.members[rec["id"]] = rec
    return success_object(serialize.member_out(rec), status=201)


@bp.route("/members", methods=["GET"])
def list_members():
    _, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk"})
    limit, offset = parse_pagination()
    studio_id = request.args.get("studio_id")
    items = list(store.members.values())
    if studio_id is not None:
        items = [m for m in items if m["studio_id"] == studio_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.member_out(m) for m in page], limit, offset, total)


@bp.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    m = get_member_or_404(mid)
    ownership_member(role, user_id, m["id"])
    return success_object(serialize.member_out(m))


@bp.route("/members/<mid>/patch-tests", methods=["GET"])
def list_member_patch_tests(mid):
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    m = get_member_or_404(mid)
    ownership_member(role, user_id, m["id"])
    limit, offset = parse_pagination()
    items = [p for p in store.consent_patch_tests.values() if p["member_id"] == m["id"]]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.patch_test_out(p) for p in page], limit, offset, total)


# --------------------------- ConsentPatchTest ------------------------------
@bp.route("/patch-tests", methods=["POST"])
def create_patch_test():
    _, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk"})
    body = get_json_body()
    member_id = require_str(body, "member_id")
    member = get_member_or_404(member_id)
    administered = parse_dt_or_400(body, "administered_utc")
    consent_signed = body.get("consent_signed")
    if not isinstance(consent_signed, bool):
        raise bad_request("consent_signed must be a boolean.")
    # If consent_signed is not true the creation is rejected as invalid request.
    if consent_signed is not True:
        raise bad_request("consent_signed must be true.")
    rec = {
        "member_id": member["id"],
        "administered_utc": administered,
        "valid_through_utc": administered + timedelta(days=PATCH_TEST_VALIDITY_DAYS),
        "consent_signed": True,
        "status": "VALID",
    }
    stamp_create(rec)
    store.consent_patch_tests[rec["id"]] = rec
    return success_object(serialize.patch_test_out(rec), status=201)


@bp.route("/patch-tests", methods=["GET"])
def list_patch_tests():
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    items = list(store.consent_patch_tests.values())
    if member_id is not None:
        items = [p for p in items if p["member_id"] == member_id]
    if role == "Member":
        items = [p for p in items if p["member_id"] == user_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.patch_test_out(p) for p in page], limit, offset, total)


@bp.route("/patch-tests/<pid>", methods=["GET"])
def get_patch_test(pid):
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "Member"})
    p = get_patch_test_or_404(pid)
    ownership_member(role, user_id, p["member_id"])
    return success_object(serialize.patch_test_out(p))


@bp.route("/patch-tests/<pid>/revoke", methods=["POST"])
def revoke_patch_test(pid):
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "Member"})
    p = get_patch_test_or_404(pid)
    ownership_member(role, user_id, p["member_id"])
    # Revoking a record that is not VALID is rejected (effective status, auto-expiry).
    if derive.effective_patch_test_status(p) != "VALID":
        raise errors.ApiError(errors.ERR_PATCH_TEST_NOT_VALID, 409, "Patch test is not VALID.")
    p["status"] = "REVOKED"
    touch(p)
    return success_object(serialize.patch_test_out(p))
