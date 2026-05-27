"""Monthly allotment routes."""

import re
from flask import Blueprint, request

from db import db, parse_iso
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.calculations import compute_monthly_allotment
from services.household_ops import bump_household
from util import (
    get_json_body, require_nonempty_str, require_int, parse_pagination, paginate,
    new_id, get_household_or_parent_404,
)


bp = Blueprint("monthly_allotments", __name__)

BENEFIT_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def _ma_view(m: dict) -> dict:
    return {
        "id": m["id"],
        "household_id": m["household_id"],
        "benefit_month": m["benefit_month"],
        "standard_allotment_cents": m.get("standard_allotment_cents", 0),
        "emergency_supplement_cents": m.get("emergency_supplement_cents", 0),
        "issued_total_cents": m.get("issued_total_cents", 0),
        "status": m["status"],
        "issued_at": m.get("issued_at"),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.route("/snap/monthly-allotments", methods=["POST"])
@require_roles("BenefitIssuer", "Caseworker")
def create_allotment(**_):
    body = get_json_body()
    hh_id = require_nonempty_str(body, "household_id")
    hh = get_household_or_parent_404(hh_id)

    benefit_month = require_nonempty_str(body, "benefit_month")
    if not BENEFIT_MONTH_RE.match(benefit_month):
        raise_api("ERR_INVALID_REQUEST", "benefit_month must be YYYY-MM")

    # Uniqueness: (household_id, benefit_month)
    for ma in db.monthly_allotments.values():
        if ma["household_id"] == hh_id and ma["benefit_month"] == benefit_month:
            raise_api(
                "ERR_DUPLICATE_ALLOTMENT_MONTH",
                f"Allotment for ({hh_id}, {benefit_month}) already exists",
            )

    # Temporal: benefit_month >= current month
    current_month = db.current_utc_iso()[:7]
    if benefit_month < current_month:
        raise_api("ERR_BENEFIT_MONTH_IN_PAST",
                  "benefit_month must be current or future month")

    standard, emergency, total = compute_monthly_allotment(hh, benefit_month)
    now = db.current_utc_iso()
    ma = {
        "id": new_id(),
        "household_id": hh_id,
        "benefit_month": benefit_month,
        "standard_allotment_cents": standard,
        "emergency_supplement_cents": emergency,
        "issued_total_cents": total,
        "status": "DRAFT",
        "issued_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.monthly_allotments[ma["id"]] = ma
    return success(_ma_view(ma), 201)


@bp.route("/snap/monthly-allotments/<ma_id>", methods=["GET"])
@require_roles("BenefitIssuer", "Caseworker", "Applicant")
def get_allotment(ma_id, _user_id, _role, **_):
    ma = db.monthly_allotments.get(ma_id)
    if ma is None:
        raise_api("ERR_NOT_FOUND", "MonthlyAllotment not found")
    if _role == "Applicant" and _user_id != ma["household_id"]:
        raise_api("ERR_FORBIDDEN", "Applicant may only view own allotments")
    return success(_ma_view(ma))


@bp.route("/snap/monthly-allotments", methods=["GET"])
@require_roles("BenefitIssuer", "Caseworker", "Applicant")
def list_allotments(_user_id, _role, **_):
    limit, offset = parse_pagination()
    hh_filter = request.args.get("household_id")
    bm_filter = request.args.get("benefit_month")
    status_filter = request.args.get("status")

    rows = list(db.monthly_allotments.values())
    if hh_filter is not None:
        rows = [r for r in rows if r["household_id"] == hh_filter]
    if bm_filter is not None:
        rows = [r for r in rows if r["benefit_month"] == bm_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if _role == "Applicant":
        rows = [r for r in rows if r["household_id"] == _user_id]

    page, total = paginate(rows, limit, offset)
    return list_success([_ma_view(r) for r in page], limit, offset, total)


@bp.route("/snap/monthly-allotments/<ma_id>/issue", methods=["POST"])
@require_roles("BenefitIssuer")
def issue_allotment(ma_id, **_):
    ma = db.monthly_allotments.get(ma_id)
    if ma is None:
        raise_api("ERR_NOT_FOUND", "MonthlyAllotment not found")

    body = get_json_body()
    if ma["status"] != "DRAFT":
        raise_api("ERR_INVALID_STATE", "MonthlyAllotment must be DRAFT to issue")

    hh = db.households.get(ma["household_id"])
    if hh is None or hh["status"] != "ACTIVE":
        raise_api("ERR_HOUSEHOLD_NOT_ACTIVE", "Host household must be ACTIVE")

    # Need at least one ACTIVE EBT card for the household
    has_active_card = any(
        card["household_id"] == hh["id"] and card["status"] == "ACTIVE"
        for card in db.ebt_cards.values()
    )
    if not has_active_card:
        raise_api(
            "ERR_INVALID_STATE",
            "Household must have at least one ACTIVE EBTCard to issue",
        )

    # Temporal: current_utc on or after first day of benefit_month
    current_month = db.current_utc_iso()[:7]
    if current_month < ma["benefit_month"]:
        raise_api("ERR_ISSUANCE_TOO_EARLY",
                  "Cannot issue before first day of benefit_month")

    # OCC: expected_household_version must match
    expected = body.get("expected_household_version", None)
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise_api("ERR_INVALID_REQUEST", "expected_household_version (int) required")
    if expected != hh["version"]:
        raise_api("ERR_STALE_HOUSEHOLD_VERSION",
                  f"Expected version {expected}, current {hh['version']}")

    # Recompute and freeze
    standard, emergency, total = compute_monthly_allotment(hh, ma["benefit_month"])
    now = db.current_utc_iso()
    ma["standard_allotment_cents"] = standard
    ma["emergency_supplement_cents"] = emergency
    ma["issued_total_cents"] = total
    ma["status"] = "ISSUED"
    ma["issued_at"] = now
    ma["updated_at"] = now
    ma["version"] = int(ma.get("version", 1)) + 1

    bump_household(hh)
    return success(_ma_view(ma))


@bp.route("/snap/monthly-allotments/<ma_id>/adjust", methods=["POST"])
@require_roles("BenefitIssuer")
def adjust_allotment(ma_id, **_):
    ma = db.monthly_allotments.get(ma_id)
    if ma is None:
        raise_api("ERR_NOT_FOUND", "MonthlyAllotment not found")
    if ma["status"] != "ISSUED":
        raise_api("ERR_INVALID_STATE", "MonthlyAllotment must be ISSUED to adjust")

    hh = db.households.get(ma["household_id"])
    if hh is None:
        raise_api("ERR_INVALID_STATE", "Household no longer exists")

    # Require a proclamation that became ACTIVE for (state_code, benefit_month) after issued_at.
    # We use the proclamation's updated_at (or created_at) as a proxy for "became ACTIVE at".
    issued_at_dt = parse_iso(ma["issued_at"]) if ma.get("issued_at") else None
    matching = None
    for proc in db.emergency_proclamations.values():
        if (proc["state_code"] == hh["state_code"]
                and proc["benefit_month"] == ma["benefit_month"]
                and proc["status"] == "ACTIVE"):
            proc_active_at = parse_iso(proc.get("updated_at") or proc["created_at"])
            if issued_at_dt is None or proc_active_at > issued_at_dt:
                matching = proc
                break

    if matching is None:
        raise_api(
            "ERR_INVALID_STATE",
            "No ACTIVE proclamation became active after issued_at",
        )

    # Re-derive emergency_supplement_cents; standard unchanged.
    _, emergency, _ = compute_monthly_allotment(hh, ma["benefit_month"])
    ma["emergency_supplement_cents"] = emergency
    ma["issued_total_cents"] = ma["standard_allotment_cents"] + emergency
    ma["status"] = "ADJUSTED"
    ma["updated_at"] = db.current_utc_iso()
    ma["version"] = int(ma.get("version", 1)) + 1
    return success(_ma_view(ma))
