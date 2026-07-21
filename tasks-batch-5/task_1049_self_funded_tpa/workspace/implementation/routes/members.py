from flask import Blueprint

import errors
import serializers
from errors import fail
from auth import require_auth, ANY_ROLE
from store import db, new_id, stamp_new, touch
from envelope import ok, created, list_response
from validation import (
    get_body, require_str, require_date, optional_date, parse_pagination,
)

bp = Blueprint("members", __name__)


@bp.post("/members")
def create_member():
    require_auth({"TPAAdmin"})
    body = get_body()
    plan_id = require_str(body, "plan_id")
    if plan_id not in db.plans:
        fail(errors.ERR_PLAN_NOT_FOUND, "Plan not found")
    m = {
        "id": new_id(),
        "plan_id": plan_id,
        "first_name": require_str(body, "first_name"),
        "last_name": require_str(body, "last_name"),
        "coverage_effective_date": require_date(body, "coverage_effective_date"),
        "coverage_term_date": optional_date(body, "coverage_term_date", None),
        "status": "ACTIVE",
        "deductible_met_cents": 0,
        "oop_met_cents": 0,
        "member_plan_paid_ytd_cents": 0,
        "spec_reimbursed_cents": 0,
    }
    stamp_new(m)
    db.members[m["id"]] = m
    return created(serializers.member(m))


@bp.get("/members/<mid>")
def get_member(mid):
    require_auth(ANY_ROLE)
    m = db.members.get(mid)
    if not m:
        fail(errors.ERR_MEMBER_NOT_FOUND, "Member not found")
    return ok(serializers.member(m))


@bp.get("/members")
def list_members():
    require_auth(ANY_ROLE)
    from flask import request
    limit, offset = parse_pagination()
    items = list(db.members.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [m for m in items if m["plan_id"] == plan_id]
    return list_response(items, serializers.member, limit, offset)


@bp.post("/members/<mid>/terminate")
def terminate_member(mid):
    require_auth({"TPAAdmin"})
    m = db.members.get(mid)
    if not m:
        fail(errors.ERR_MEMBER_NOT_FOUND, "Member not found")
    body = get_body()
    term_date = require_date(body, "termination_date")
    if m["status"] != "ACTIVE":
        fail(errors.ERR_INVALID_STATE, "Member is not ACTIVE")
    m["coverage_term_date"] = term_date
    m["status"] = "TERMINATED"
    touch(m)
    return ok(serializers.member(m))
