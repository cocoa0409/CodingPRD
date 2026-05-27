"""ABAWD waiver routes."""

import re
from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from util import (
    get_json_body, require_nonempty_str, require_int, parse_pagination, paginate, new_id,
    get_member_or_parent_404,
)


bp = Blueprint("abawd_waivers", __name__)

QUARTER_RE = re.compile(r"^[0-9]{4}-Q[1-4]$")


def _waiver_view(w: dict) -> dict:
    return {
        "id": w["id"],
        "household_member_id": w["household_member_id"],
        "quarter": w["quarter"],
        "county_unemployment_pct": w["county_unemployment_pct"],
        "monthly_work_hours": w["monthly_work_hours"],
        "status": w["status"],
        "decision_reason": w.get("decision_reason"),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


@bp.route("/snap/abawd-waivers", methods=["POST"])
@require_roles("Caseworker", "Applicant")
def create_waiver(_user_id, _role, **_):
    body = get_json_body()
    member_id = require_nonempty_str(body, "household_member_id")
    member = get_member_or_parent_404(member_id)
    if _role == "Applicant" and _user_id != member["household_id"]:
        raise_api("ERR_FORBIDDEN", "Applicant may only request own member's waiver")

    quarter = require_nonempty_str(body, "quarter")
    if not QUARTER_RE.match(quarter):
        raise_api("ERR_INVALID_REQUEST", "quarter must be YYYY-Q[1-4]")

    pct = body.get("county_unemployment_pct", None)
    if pct is None or isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise_api("ERR_INVALID_REQUEST", "county_unemployment_pct must be a number")
    if pct < 0 or pct > 50:
        raise_api("ERR_INVALID_REQUEST",
                  "county_unemployment_pct must be between 0 and 50")

    hours = require_int(body, "monthly_work_hours", min_value=0)

    for w in db.abawd_waivers.values():
        if w["household_member_id"] == member_id and w["quarter"] == quarter:
            raise_api("ERR_DUPLICATE_WAIVER_QUARTER",
                      f"Waiver for ({member_id}, {quarter}) already exists")

    now = db.current_utc_iso()
    w = {
        "id": new_id(),
        "household_member_id": member_id,
        "quarter": quarter,
        "county_unemployment_pct": float(pct),
        "monthly_work_hours": hours,
        "status": "PENDING",
        "decision_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.abawd_waivers[w["id"]] = w
    return success(_waiver_view(w), 201)


@bp.route("/snap/abawd-waivers/<wv_id>", methods=["GET"])
@require_roles("Caseworker", "Applicant")
def get_waiver(wv_id, _user_id, _role, **_):
    w = db.abawd_waivers.get(wv_id)
    if w is None:
        raise_api("ERR_NOT_FOUND", "ABAWDWaiver not found")
    if _role == "Applicant":
        member = db.members.get(w["household_member_id"])
        if member is None or _user_id != member["household_id"]:
            raise_api("ERR_FORBIDDEN", "Applicant may only view own member's waiver")
    return success(_waiver_view(w))


@bp.route("/snap/abawd-waivers", methods=["GET"])
@require_roles("Caseworker", "Applicant")
def list_waivers(_user_id, _role, **_):
    limit, offset = parse_pagination()
    member_filter = request.args.get("household_member_id")
    quarter_filter = request.args.get("quarter")
    status_filter = request.args.get("status")

    rows = list(db.abawd_waivers.values())
    if member_filter is not None:
        rows = [r for r in rows if r["household_member_id"] == member_filter]
    if quarter_filter is not None:
        rows = [r for r in rows if r["quarter"] == quarter_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if _role == "Applicant":
        # Filter to waivers whose member belongs to the applicant's household
        own_member_ids = {m["id"] for m in db.members.values()
                          if m["household_id"] == _user_id}
        rows = [r for r in rows if r["household_member_id"] in own_member_ids]

    page, total = paginate(rows, limit, offset)
    return list_success([_waiver_view(r) for r in page], limit, offset, total)


@bp.route("/snap/abawd-waivers/<wv_id>/approve", methods=["POST"])
@require_roles("Caseworker")
def approve_waiver(wv_id, **_):
    w = db.abawd_waivers.get(wv_id)
    if w is None:
        raise_api("ERR_NOT_FOUND", "ABAWDWaiver not found")

    body = get_json_body()
    if w["status"] != "PENDING":
        raise_api("ERR_INVALID_STATE", "ABAWDWaiver must be PENDING to approve")

    # ABAWD eligibility: county_unemployment_pct >= 10.00 OR monthly_work_hours >= 80
    if not (w["county_unemployment_pct"] >= 10.00 or w["monthly_work_hours"] >= 80):
        raise_api(
            "ERR_INVALID_STATE",
            "ABAWD eligibility not met: need county_unemployment_pct >= 10 or monthly_work_hours >= 80",
        )

    decision_reason = require_nonempty_str(body, "decision_reason")
    w["status"] = "APPROVED"
    w["decision_reason"] = decision_reason
    w["updated_at"] = db.current_utc_iso()
    w["version"] = int(w.get("version", 1)) + 1
    return success(_waiver_view(w))


@bp.route("/snap/abawd-waivers/<wv_id>/deny", methods=["POST"])
@require_roles("Caseworker")
def deny_waiver(wv_id, **_):
    w = db.abawd_waivers.get(wv_id)
    if w is None:
        raise_api("ERR_NOT_FOUND", "ABAWDWaiver not found")

    body = get_json_body()
    if w["status"] != "PENDING":
        raise_api("ERR_INVALID_STATE", "ABAWDWaiver must be PENDING to deny")
    decision_reason = require_nonempty_str(body, "decision_reason")
    w["status"] = "DENIED"
    w["decision_reason"] = decision_reason
    w["updated_at"] = db.current_utc_iso()
    w["version"] = int(w.get("version", 1)) + 1
    return success(_waiver_view(w))


@bp.route("/snap/abawd-waivers/<wv_id>/revoke", methods=["POST"])
@require_roles("Caseworker")
def revoke_waiver(wv_id, **_):
    w = db.abawd_waivers.get(wv_id)
    if w is None:
        raise_api("ERR_NOT_FOUND", "ABAWDWaiver not found")
    if w["status"] != "APPROVED":
        raise_api("ERR_INVALID_STATE", "ABAWDWaiver must be APPROVED to revoke")
    w["status"] = "REVOKED"
    w["updated_at"] = db.current_utc_iso()
    w["version"] = int(w.get("version", 1)) + 1
    return success(_waiver_view(w))
