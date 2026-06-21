"""HouseholdMember routes."""

from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.household_ops import bump_household, recompute_household_totals
from util import (
    get_json_body, require_nonempty_str, optional_str, optional_bool,
    optional_int, parse_pagination, paginate, new_id, get_household_or_parent_404,
)


bp = Blueprint("members", __name__)

VALID_RELATIONSHIPS = {"HEAD", "SPOUSE", "CHILD", "PARENT", "OTHER"}


def _member_view(m: dict) -> dict:
    return {
        "id": m["id"],
        "household_id": m["household_id"],
        "full_name": m["full_name"],
        "date_of_birth": m["date_of_birth"],
        "relationship": m["relationship"],
        "monthly_earned_income_cents": m.get("monthly_earned_income_cents", 0),
        "monthly_unearned_income_cents": m.get("monthly_unearned_income_cents", 0),
        "disabled": m.get("disabled", False),
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.route("/snap/household-members", methods=["POST"])
@require_roles("Caseworker")
def create_member(**_):
    body = get_json_body()
    hh_id = require_nonempty_str(body, "household_id")
    hh = get_household_or_parent_404(hh_id)

    full_name = require_nonempty_str(body, "full_name")
    dob = require_nonempty_str(body, "date_of_birth")
    relationship = require_nonempty_str(body, "relationship")
    if relationship not in VALID_RELATIONSHIPS:
        raise_api("ERR_INVALID_REQUEST", "relationship not in allowed enum")

    earned = optional_int(body, "monthly_earned_income_cents", default=0, min_value=0)
    unearned = optional_int(body, "monthly_unearned_income_cents", default=0, min_value=0)
    disabled = optional_bool(body, "disabled", default=False)

    now = db.current_utc_iso()
    m = {
        "id": new_id(),
        "household_id": hh_id,
        "full_name": full_name,
        "date_of_birth": dob,
        "relationship": relationship,
        "monthly_earned_income_cents": int(earned),
        "monthly_unearned_income_cents": int(unearned),
        "disabled": disabled,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.members[m["id"]] = m

    recompute_household_totals(hh)
    bump_household(hh)

    return success(_member_view(m), 201)


@bp.route("/snap/household-members/<member_id>", methods=["GET"])
@require_roles("Caseworker", "Applicant", "FraudInvestigator")
def get_member(member_id, _user_id, _role, **_):
    m = db.members.get(member_id)
    if m is None:
        raise_api("ERR_NOT_FOUND", "HouseholdMember not found")
    if _role == "Applicant" and _user_id != m["household_id"]:
        raise_api("ERR_FORBIDDEN", "Applicant may only view own members")
    return success(_member_view(m))


@bp.route("/snap/household-members", methods=["GET"])
@require_roles("Caseworker", "Applicant", "FraudInvestigator")
def list_members(_user_id, _role, **_):
    limit, offset = parse_pagination()
    hh_filter = request.args.get("household_id")
    status_filter = request.args.get("status")

    rows = list(db.members.values())
    if hh_filter is not None:
        rows = [r for r in rows if r["household_id"] == hh_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if _role == "Applicant":
        rows = [r for r in rows if r["household_id"] == _user_id]

    page, total = paginate(rows, limit, offset)
    return list_success([_member_view(r) for r in page], limit, offset, total)


@bp.route("/snap/household-members/<member_id>", methods=["PATCH"])
@require_roles("Caseworker")
def update_member(member_id, **_):
    m = db.members.get(member_id)
    if m is None:
        raise_api("ERR_NOT_FOUND", "HouseholdMember not found")

    body = get_json_body()
    changed = False
    recompute_needed = False

    if "monthly_earned_income_cents" in body:
        v = body["monthly_earned_income_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise_api("ERR_INVALID_REQUEST", "monthly_earned_income_cents must be int >= 0")
        if m["monthly_earned_income_cents"] != v:
            m["monthly_earned_income_cents"] = v
            changed = True
            recompute_needed = True

    if "monthly_unearned_income_cents" in body:
        v = body["monthly_unearned_income_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise_api("ERR_INVALID_REQUEST", "monthly_unearned_income_cents must be int >= 0")
        if m["monthly_unearned_income_cents"] != v:
            m["monthly_unearned_income_cents"] = v
            changed = True
            recompute_needed = True

    if "disabled" in body:
        v = body["disabled"]
        if not isinstance(v, bool):
            raise_api("ERR_INVALID_REQUEST", "disabled must be a boolean")
        if m["disabled"] != v:
            m["disabled"] = v
            changed = True
            recompute_needed = True  # income deductions unaffected, but PRD lists it as triggering recompute

    if "status" in body:
        v = body["status"]
        if v not in ("ACTIVE", "REMOVED"):
            raise_api("ERR_INVALID_REQUEST", "status must be ACTIVE or REMOVED")
        if m["status"] != v:
            m["status"] = v
            changed = True
            recompute_needed = True

    if changed:
        m["updated_at"] = db.current_utc_iso()
        m["version"] = int(m.get("version", 1)) + 1
        hh = db.households.get(m["household_id"])
        if hh is not None and recompute_needed:
            recompute_household_totals(hh)
            bump_household(hh)
        elif hh is not None:
            bump_household(hh)

    return success(_member_view(m))
