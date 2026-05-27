"""Emergency allotment proclamation routes."""

import re
from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from util import (
    get_json_body, require_nonempty_str, optional_int, parse_pagination, paginate, new_id,
)


bp = Blueprint("emergency_allotments", __name__)

BENEFIT_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
VALID_STATES = {"CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI"}


def _proc_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "state_code": p["state_code"],
        "benefit_month": p["benefit_month"],
        "min_supplement_cents": p["min_supplement_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/snap/emergency-allotments", methods=["POST"])
@require_roles("PolicyAdmin")
def create_proclamation(**_):
    body = get_json_body()
    state_code = require_nonempty_str(body, "state_code")
    benefit_month = require_nonempty_str(body, "benefit_month")
    if state_code not in VALID_STATES:
        raise_api("ERR_INVALID_REQUEST", "state_code not in allowed enum")
    if not BENEFIT_MONTH_RE.match(benefit_month):
        raise_api("ERR_INVALID_REQUEST", "benefit_month must be YYYY-MM")
    min_supp = optional_int(body, "min_supplement_cents", default=9500, min_value=0)

    for p in db.emergency_proclamations.values():
        if p["state_code"] == state_code and p["benefit_month"] == benefit_month:
            raise_api(
                "ERR_DUPLICATE_PROCLAMATION",
                f"Proclamation for ({state_code}, {benefit_month}) already exists",
            )

    now = db.current_utc_iso()
    p = {
        "id": new_id(),
        "state_code": state_code,
        "benefit_month": benefit_month,
        "min_supplement_cents": int(min_supp),
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.emergency_proclamations[p["id"]] = p
    return success(_proc_view(p), 201)


@bp.route("/snap/emergency-allotments/<p_id>", methods=["GET"])
@require_roles("PolicyAdmin", "BenefitIssuer", "Caseworker")
def get_proclamation(p_id, **_):
    p = db.emergency_proclamations.get(p_id)
    if p is None:
        raise_api("ERR_NOT_FOUND", "EmergencyAllotmentProclamation not found")
    return success(_proc_view(p))


@bp.route("/snap/emergency-allotments", methods=["GET"])
@require_roles("PolicyAdmin", "BenefitIssuer", "Caseworker")
def list_proclamations(**_):
    limit, offset = parse_pagination()
    state_filter = request.args.get("state_code")
    bm_filter = request.args.get("benefit_month")
    status_filter = request.args.get("status")

    rows = list(db.emergency_proclamations.values())
    if state_filter is not None:
        rows = [r for r in rows if r["state_code"] == state_filter]
    if bm_filter is not None:
        rows = [r for r in rows if r["benefit_month"] == bm_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]

    page, total = paginate(rows, limit, offset)
    return list_success([_proc_view(r) for r in page], limit, offset, total)


@bp.route("/snap/emergency-allotments/<p_id>/activate", methods=["POST"])
@require_roles("PolicyAdmin")
def activate_proclamation(p_id, **_):
    p = db.emergency_proclamations.get(p_id)
    if p is None:
        raise_api("ERR_NOT_FOUND", "EmergencyAllotmentProclamation not found")
    if p["status"] != "DRAFT":
        raise_api("ERR_INVALID_STATE", "Proclamation must be DRAFT to activate")

    current_month = db.current_utc_iso()[:7]
    if p["benefit_month"] < current_month:
        raise_api("ERR_INVALID_STATE",
                  "Proclamation benefit_month must be current or future month at activation")

    p["status"] = "ACTIVE"
    p["updated_at"] = db.current_utc_iso()
    p["version"] = int(p.get("version", 1)) + 1
    return success(_proc_view(p))
