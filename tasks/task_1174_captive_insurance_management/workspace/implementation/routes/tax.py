"""TaxPosition routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    adjust_governance,
    body,
    compute_risk_distribution,
    get_captive,
    get_tax_position,
    req_enum,
    req_int,
    req_str,
    stamp_new,
    touch,
    touch_captive,
)

bp = Blueprint("tax", __name__)

READ_ROLES = ("CaptiveManager", "TaxAdvisor")


@bp.post("/api/captives/<captiveId>/tax-positions")
def create_tax_position(captiveId):
    user_id, role = require_roles("TaxAdvisor")
    get_captive(captiveId)
    data = body()
    year = req_int(data, "tax_year")
    ptype = req_enum(data, "position_type", C.POSITION_TYPES)
    description = req_str(data, "position_description")

    pos = stamp_new()
    pos.update({
        "captive_id": captiveId,
        "tax_year": year,
        "position_type": ptype,
        "position_description": description,
        "premium_deductibility_pct": 0.0,
        "risk_distribution_test_result": None,
        "insured_entities_count": 0,
        "third_party_premium_pct": 0.0,
        "premium_threshold_met": False,
        "reporting_position": None,
        "disclosure_required": False,
        "status": "DRAFT",
    })
    db.tax_positions[pos["id"]] = pos
    log(captiveId, "TAX_POSITION_CHANGE", "TaxPosition", pos["id"], role,
        user_id, "Tax position created in DRAFT", None, "DRAFT")
    return ok(pos, 201)


@bp.get("/api/captives/<captiveId>/tax-positions")
def list_tax_positions(captiveId):
    require_roles(*READ_ROLES)
    get_captive(captiveId)
    items = [p for p in db.tax_positions.values() if p["captive_id"] == captiveId]
    year = request.args.get("tax_year")
    if year:
        try:
            yv = int(year)
            items = [p for p in items if int(p["tax_year"]) == yv]
        except ValueError:
            pass
    ptype = request.args.get("position_type")
    if ptype:
        items = [p for p in items if p["position_type"] == ptype]
    items.sort(key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/tax-positions/<positionId>")
def get_tax_position_route(captiveId, positionId):
    require_roles(*READ_ROLES)
    captive = get_captive(captiveId)
    return ok(get_tax_position(captive, positionId), 200)


@bp.post("/api/captives/<captiveId>/tax-positions/<positionId>/analyze")
def analyze_tax_position(captiveId, positionId):
    user_id, role = require_roles("TaxAdvisor")
    captive = get_captive(captiveId)
    pos = get_tax_position(captive, positionId)
    if pos["status"] != "DRAFT":
        raise ApiError("ERR_TAX_POSITION_NOT_DRAFT",
                       "Tax position must be in DRAFT state")
    analysis = compute_risk_distribution(captive)
    if (captive.get("tax_classification") == "MICRO_CAPTIVE_831B"
            and analysis["total_premium_cents"] > C.MICRO_CAPTIVE_PREMIUM_LIMIT):
        raise ApiError("ERR_PREMIUM_THRESHOLD_EXCEEDED",
                       "Premium exceeds micro-captive 831(b) threshold")
    prev = pos["status"]
    pos["risk_distribution_test_result"] = analysis["risk_distribution_test_result"]
    pos["premium_deductibility_pct"] = analysis["premium_deductibility_pct"]
    pos["insured_entities_count"] = analysis["insured_entities_count"]
    pos["third_party_premium_pct"] = analysis["third_party_premium_pct"]
    pos["premium_threshold_met"] = analysis["premium_threshold_met"]
    pos["disclosure_required"] = analysis["disclosure_required"]
    pos["status"] = "ANALYZED"
    touch(pos)
    captive["risk_distribution_score"] = analysis["risk_distribution_score"]
    touch_captive(captive)
    log(captiveId, "TAX_POSITION_CHANGE", "TaxPosition", positionId, role,
        user_id, "Tax position analyzed; risk distribution computed", prev,
        "ANALYZED")
    return ok(pos, 200)


@bp.post("/api/captives/<captiveId>/tax-positions/<positionId>/issue-opinion")
def issue_opinion(captiveId, positionId):
    user_id, role = require_roles("TaxAdvisor")
    captive = get_captive(captiveId)
    pos = get_tax_position(captive, positionId)
    if pos["status"] != "ANALYZED":
        raise ApiError("ERR_TAX_POSITION_NOT_ANALYZED",
                       "Tax position must be in ANALYZED state")
    data = body()
    reporting = data.get("reporting_position")
    if reporting is None:
        raise ApiError("ERR_NO_REPORTING_POSITION",
                       "No reporting position specified for tax opinion")
    if reporting not in C.REPORTING_POSITIONS:
        raise ApiError("ERR_INVALID_REQUEST",
                       f"reporting_position must be one of {C.REPORTING_POSITIONS}")
    prev = pos["status"]
    pos["reporting_position"] = reporting
    pos["status"] = "OPINION_ISSUED"
    touch(pos)
    analysis = compute_risk_distribution(captive)
    captive["risk_distribution_score"] = analysis["risk_distribution_score"]
    touch_captive(captive)
    log(captiveId, "TAX_POSITION_CHANGE", "TaxPosition", positionId, role,
        user_id, f"Opinion issued: {reporting}", prev, "OPINION_ISSUED")
    return ok(pos, 200)


@bp.post("/api/captives/<captiveId>/tax-positions/<positionId>/file")
def file_tax_position(captiveId, positionId):
    user_id, role = require_roles("CaptiveManager")
    captive = get_captive(captiveId)
    pos = get_tax_position(captive, positionId)
    if pos["status"] != "OPINION_ISSUED":
        raise ApiError("ERR_TAX_POSITION_NOT_OPINION_ISSUED",
                       "Tax position must be in OPINION_ISSUED state")
    prev = pos["status"]
    pos["status"] = "FILED"
    touch(pos)
    log(captiveId, "FILING_SUBMITTED", "TaxPosition", positionId, role,
        user_id, "Tax position filed", prev, "FILED")
    return ok(pos, 200)


@bp.post("/api/captives/<captiveId>/tax-positions/<positionId>/challenge")
def challenge_tax_position(captiveId, positionId):
    user_id, role = require_roles("TaxAdvisor")
    captive = get_captive(captiveId)
    pos = get_tax_position(captive, positionId)
    if pos["status"] != "FILED":
        raise ApiError("ERR_TAX_POSITION_NOT_FILED",
                       "Tax position must be in FILED state")
    prev = pos["status"]
    pos["status"] = "CHALLENGED"
    touch(pos)
    # Spawn a fresh DRAFT position for the same tax_year + position_type.
    new_pos = stamp_new()
    new_pos.update({
        "captive_id": captiveId,
        "tax_year": pos["tax_year"],
        "position_type": pos["position_type"],
        "position_description": pos.get("position_description"),
        "premium_deductibility_pct": 0.0,
        "risk_distribution_test_result": None,
        "insured_entities_count": 0,
        "third_party_premium_pct": 0.0,
        "premium_threshold_met": False,
        "reporting_position": None,
        "disclosure_required": False,
        "status": "DRAFT",
    })
    db.tax_positions[new_pos["id"]] = new_pos
    adjust_governance(captive, -15)
    touch_captive(captive)
    log(captiveId, "TAX_POSITION_CHANGE", "TaxPosition", positionId, role,
        user_id,
        "Tax position challenged; new DRAFT spawned; governance score -15",
        prev, "CHALLENGED")
    return ok(pos, 200)
