"""Landlord agreements (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint, request, g

import db
from auth import require, body
from validation import (
    get_or_404, req_str, req_int, req_date, require_after,
)
from responses import success, list_response
from serializers import serialize
from errors import ApiError
from constants import UNIT_BUFFER_DAYS

bp = Blueprint("agreements", __name__)


@bp.post("/agreements")
@require("Landlord")
def create_agreement():
    b = body()
    # Existence (404) left to right: guarantee_id then landlord_id.
    guarantee = None
    if b.get("guarantee_id") is not None:
        guarantee = get_or_404(db.guarantees, b["guarantee_id"])
    if b.get("landlord_id") is not None:
        get_or_404(db.landlords, b["landlord_id"])

    landlord_id = req_str(b, "landlord_id")
    # ownership: body landlord_id must equal the acting landlord
    if landlord_id != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    guarantee_id = req_str(b, "guarantee_id")
    unit_id = req_str(b, "unit_id")
    start = req_date(b, "coverage_start_date")
    end = req_date(b, "coverage_end_date")
    require_after(start, end)
    max_coverage = req_int(b, "max_coverage_cents", nonneg=True)
    notice_period = req_int(b, "notice_period_days", positive=True)

    # unit_id must match the guarantee's unit_id
    if guarantee is not None and unit_id != guarantee["unit_id"]:
        raise ApiError("ERR_INVALID_REQUEST")

    # unit-overlap: same unit, existing ACTIVE agreements must be >= buffer apart
    buffer = timedelta(days=UNIT_BUFFER_DAYS)
    for ag in db.agreements.values():
        if ag["unit_id"] != unit_id or ag["status"] != "ACTIVE":
            continue
        s1 = db.parse_iso(ag["coverage_start_date"])
        e1 = db.parse_iso(ag["coverage_end_date"])
        apart = (start - e1 >= buffer) or (s1 - end >= buffer)
        if not apart:
            raise ApiError("ERR_UNIT_COVERAGE_OVERLAP")

    ag = {
        "guarantee_id": guarantee_id,
        "landlord_id": landlord_id,
        "unit_id": unit_id,
        "coverage_start_date": b["coverage_start_date"],
        "coverage_end_date": b["coverage_end_date"],
        "max_coverage_cents": max_coverage,
        "notice_period_days": notice_period,
        "status": "DRAFT",
    }
    db.stamp_common(ag)
    db.agreements[ag["id"]] = ag
    return success(serialize(ag), 201)


@bp.get("/agreements/<aid>")
@require("Landlord", "Underwriter", "PlatformAdmin")
def get_agreement(aid):
    ag = get_or_404(db.agreements, aid)
    return success(serialize(ag), 200)


@bp.get("/agreements")
@require("Landlord", "Underwriter", "PlatformAdmin")
def list_agreements():
    args = request.args
    items = list(db.agreements.values())
    for key in ("guarantee_id", "landlord_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [x for x in items if x.get(key) == val]
    return list_response(items, args)


@bp.post("/agreements/<aid>/sign")
@require("Landlord")
def sign_agreement(aid):
    ag = get_or_404(db.agreements, aid)
    if ag["landlord_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if ag["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    ag["status"] = "SIGNED"
    db.touch(ag)
    return success(serialize(ag), 200)


@bp.post("/agreements/<aid>/countersign")
@require("Underwriter")
def countersign_agreement(aid):
    ag = get_or_404(db.agreements, aid)
    if ag["status"] != "SIGNED":
        raise ApiError("ERR_INVALID_STATE")
    guarantee = db.guarantees.get(ag["guarantee_id"])
    if guarantee is None or guarantee["status"] != "APPROVED":
        raise ApiError("ERR_GUARANTEE_NOT_APPROVED")

    guarantee["landlord_id"] = ag["landlord_id"]
    db.touch(guarantee)
    ag["status"] = "ACTIVE"
    db.touch(ag)
    return success(serialize(ag), 200)
