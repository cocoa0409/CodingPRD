"""Logical clock, portfolios, landlords."""
from flask import Blueprint, request, g

import db
from auth import require, body
from validation import get_or_404, req_str, req_int, req_date
from responses import success
from serializers import serialize
from services import recompute_portfolio

bp = Blueprint("misc", __name__)


# --- Logical clock (PRD 2.10) ---
@bp.post("/_clock/set_current_utc")
@require("PlatformAdmin")
def set_clock():
    b = body()
    dt = req_date(b, "to_iso8601")
    db.set_clock(dt)
    return success({"current_utc": db.now_iso()}, 200)


# --- Portfolios (PRD 2.7) ---
@bp.post("/portfolios")
@require("PlatformAdmin")
def create_portfolio():
    b = body()
    name = req_str(b, "name")
    cap = req_int(b, "exposure_cap_cents", positive=True)
    p = {
        "name": name,
        "exposure_cap_cents": cap,
        "total_active_coverage_cents": 0,
        "total_outstanding_recovery_cents": 0,
        "risk_weighted_exposure_cents": 0,
        "posture": "OPEN",
    }
    db.stamp_common(p)
    db.portfolios[p["id"]] = p
    return success(serialize(p), 201)


@bp.get("/portfolios/<pid>")
@require("PlatformAdmin", "ComplianceOfficer", "Underwriter")
def get_portfolio(pid):
    p = get_or_404(db.portfolios, pid)
    return success(serialize(p), 200)


@bp.post("/portfolios/<pid>/recompute-risk")
@require("ComplianceOfficer", "PlatformAdmin")
def recompute_risk(pid):
    p = get_or_404(db.portfolios, pid)
    recompute_portfolio(p)
    return success(serialize(p), 200)


# --- Landlords (PRD 3.3) ---
@bp.post("/landlords")
@require("PlatformAdmin")
def create_landlord():
    b = body()
    legal_name = req_str(b, "legal_name")
    email = req_str(b, "email")
    l = {"legal_name": legal_name, "email": email, "status": "ACTIVE"}
    db.stamp_common(l)
    db.landlords[l["id"]] = l
    return success(serialize(l), 201)


@bp.get("/landlords/<lid>")
@require("PlatformAdmin", "Underwriter", "Landlord")
def get_landlord(lid):
    l = get_or_404(db.landlords, lid)
    return success(serialize(l), 200)
