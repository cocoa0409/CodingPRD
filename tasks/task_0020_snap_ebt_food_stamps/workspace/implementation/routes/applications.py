"""Application routes including ABAWD/income preconditions on approve."""

from datetime import timedelta
from flask import Blueprint, request

from db import db, parse_iso, iso_from_datetime
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.calculations import (
    net_monthly_income, net_income_limit_for_size,
)
from services.household_ops import bump_household
from util import (
    get_json_body, require_nonempty_str, parse_pagination, paginate, new_id,
    get_household_or_parent_404, new_id as _new_id,
)


bp = Blueprint("applications", __name__)


def _app_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "household_id": a["household_id"],
        "applied_at": a.get("applied_at"),
        "status": a["status"],
        "caseworker_id": a.get("caseworker_id"),
        "decision_reason": a.get("decision_reason"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def _ebt_card_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "household_id": c["household_id"],
        "pan_last4": c.get("pan_last4"),
        "status": c["status"],
        "replaced_by_card_id": c.get("replaced_by_card_id"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/snap/applications", methods=["POST"])
@require_roles("Caseworker", "Applicant")
def create_application(_user_id, _role, **_):
    body = get_json_body()
    hh_id = require_nonempty_str(body, "household_id")
    hh = get_household_or_parent_404(hh_id)
    if _role == "Applicant" and _user_id != hh_id:
        raise_api("ERR_FORBIDDEN", "Applicant may only create application for own household")

    now = db.current_utc_iso()
    a = {
        "id": new_id(),
        "household_id": hh_id,
        "applied_at": None,
        "status": "DRAFT",
        "caseworker_id": None,
        "decision_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.applications[a["id"]] = a
    return success(_app_view(a), 201)


@bp.route("/snap/applications/<app_id>", methods=["GET"])
@require_roles("Caseworker", "Applicant")
def get_application(app_id, _user_id, _role, **_):
    a = db.applications.get(app_id)
    if a is None:
        raise_api("ERR_NOT_FOUND", "Application not found")
    if _role == "Applicant" and _user_id != a["household_id"]:
        raise_api("ERR_FORBIDDEN", "Applicant may only view own application")
    return success(_app_view(a))


@bp.route("/snap/applications", methods=["GET"])
@require_roles("Caseworker", "Applicant")
def list_applications(_user_id, _role, **_):
    limit, offset = parse_pagination()
    hh_filter = request.args.get("household_id")
    status_filter = request.args.get("status")

    rows = list(db.applications.values())
    if hh_filter is not None:
        rows = [r for r in rows if r["household_id"] == hh_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if _role == "Applicant":
        rows = [r for r in rows if r["household_id"] == _user_id]

    page, total = paginate(rows, limit, offset)
    return list_success([_app_view(r) for r in page], limit, offset, total)


@bp.route("/snap/applications/<app_id>/submit", methods=["POST"])
@require_roles("Applicant", "Caseworker")
def submit_application(app_id, _user_id, _role, **_):
    a = db.applications.get(app_id)
    if a is None:
        raise_api("ERR_NOT_FOUND", "Application not found")
    if a["status"] != "DRAFT":
        raise_api("ERR_INVALID_STATE", "Application must be DRAFT to submit")
    hh = db.households.get(a["household_id"])
    if hh is None:
        raise_api("ERR_INVALID_STATE", "Household no longer exists")
    if hh["status"] != "PENDING":
        raise_api("ERR_INVALID_STATE", "Household must be PENDING for application submission")
    # Need at least one ACTIVE member
    if hh.get("size", 0) < 1:
        raise_api("ERR_INVALID_STATE", "Household must have at least one ACTIVE member")

    if _role == "Applicant" and _user_id != hh["id"]:
        raise_api("ERR_FORBIDDEN", "Applicant may only submit own application")

    now = db.current_utc_iso()
    a["status"] = "SUBMITTED"
    a["applied_at"] = now
    a["updated_at"] = now
    a["version"] = int(a.get("version", 1)) + 1

    # Refresh Household.updated_at
    hh["updated_at"] = now

    return success(_app_view(a))


def _current_quarter_str(iso_now: str) -> str:
    # YYYY-MM -> YYYY-Q[1..4]
    year = int(iso_now[:4])
    month = int(iso_now[5:7])
    quarter = (month - 1) // 3 + 1
    return f"{year}-Q{quarter}"


def _ages(dob_iso: str, ref_dt) -> int:
    dob_dt = parse_iso(dob_iso)
    years = ref_dt.year - dob_dt.year
    if (ref_dt.month, ref_dt.day) < (dob_dt.month, dob_dt.day):
        years -= 1
    return years


def _is_abawd(member: dict, household_id: str, ref_dt) -> bool:
    """ABAWD = age 18..49 AND not disabled AND household has no member <18."""
    if member.get("disabled", False):
        return False
    age = _ages(member["date_of_birth"], ref_dt)
    if age < 18 or age > 49:
        return False
    # Household has no ACTIVE child under 18
    for m in db.members.values():
        if m["household_id"] != household_id:
            continue
        if m.get("status") != "ACTIVE":
            continue
        if _ages(m["date_of_birth"], ref_dt) < 18:
            return False
    return True


def _check_abawd(hh_id: str):
    """Raise ERR_ABAWD_REQUIREMENT_UNMET if any ABAWD lacks an OK waiver."""
    now_dt = db.current_utc_dt()
    quarter = _current_quarter_str(db.current_utc_iso())
    actives = [m for m in db.members.values()
               if m["household_id"] == hh_id and m["status"] == "ACTIVE"]
    for member in actives:
        if not _is_abawd(member, hh_id, now_dt):
            continue
        # Look for waivers for (this member, this quarter)
        relevant = [w for w in db.abawd_waivers.values()
                    if w["household_member_id"] == member["id"] and w["quarter"] == quarter]
        ok = False
        for w in relevant:
            if w["status"] == "APPROVED":
                ok = True
                break
            if w["status"] == "PENDING" and int(w.get("monthly_work_hours", 0) or 0) >= 80:
                ok = True
                break
        if not ok:
            raise_api(
                "ERR_ABAWD_REQUIREMENT_UNMET",
                f"ABAWD member {member['id']} lacks valid waiver/work hours for {quarter}",
            )


@bp.route("/snap/applications/<app_id>/approve", methods=["POST"])
@require_roles("Caseworker")
def approve_application(app_id, _user_id, _role, **_):
    a = db.applications.get(app_id)
    if a is None:
        raise_api("ERR_NOT_FOUND", "Application not found")

    body = get_json_body()
    if a["status"] != "SUBMITTED":
        raise_api("ERR_INVALID_STATE", "Application must be SUBMITTED to approve")

    hh = db.households.get(a["household_id"])
    if hh is None:
        raise_api("ERR_INVALID_STATE", "Household no longer exists")

    # Priority 16: ABAWD requirement
    _check_abawd(hh["id"])

    # Priority 17: income limit (variant=LIMIT_CHECK)
    limit_net = net_monthly_income(hh, variant="LIMIT_CHECK")
    size = max(hh.get("size", 0), 1)
    income_limit = net_income_limit_for_size(size)
    if limit_net > income_limit:
        raise_api("ERR_INCOME_LIMIT_EXCEEDED",
                  f"Net income {limit_net} exceeds limit {income_limit}")

    decision_reason = require_nonempty_str(body, "decision_reason")

    now = db.current_utc_iso()
    now_dt = db.current_utc_dt()

    # Application transition
    a["status"] = "APPROVED"
    a["caseworker_id"] = _user_id
    a["decision_reason"] = decision_reason
    a["updated_at"] = now
    a["version"] = int(a.get("version", 1)) + 1

    # Household: PENDING -> CERTIFIED -> ACTIVE (auto-advance, in same request).
    hh["status"] = "ACTIVE"
    # certification_end_date = current_utc + 12 months (approximation: 365 days)
    cert_end = now_dt + timedelta(days=365)
    hh["certification_end_date"] = iso_from_datetime(cert_end)
    bump_household(hh)

    # Side effect: create EBT card with status PENDING_ISSUE
    card_now = db.current_utc_iso()
    card = {
        "id": new_id(),
        "household_id": hh["id"],
        "pan_last4": None,
        "status": "PENDING_ISSUE",
        "replaced_by_card_id": None,
        "created_at": card_now,
        "updated_at": card_now,
        "version": 1,
    }
    db.ebt_cards[card["id"]] = card

    return success(_app_view(a))


@bp.route("/snap/applications/<app_id>/deny", methods=["POST"])
@require_roles("Caseworker")
def deny_application(app_id, _user_id, _role, **_):
    a = db.applications.get(app_id)
    if a is None:
        raise_api("ERR_NOT_FOUND", "Application not found")

    body = get_json_body()
    if a["status"] != "SUBMITTED":
        raise_api("ERR_INVALID_STATE", "Application must be SUBMITTED to deny")
    decision_reason = require_nonempty_str(body, "decision_reason")

    hh = db.households.get(a["household_id"])
    if hh is None:
        raise_api("ERR_INVALID_STATE", "Household no longer exists")

    now = db.current_utc_iso()
    a["status"] = "DENIED"
    a["caseworker_id"] = _user_id
    a["decision_reason"] = decision_reason
    a["updated_at"] = now
    a["version"] = int(a.get("version", 1)) + 1

    hh["status"] = "TERMINATED"
    bump_household(hh)

    return success(_app_view(a))
