"""Interview guides, rubrics, and revision chains (PRD §3.3)."""
from decimal import Decimal

import db
import serializers
import util
from errors import api_err, err_invalid_request, err_not_found
from flask import Blueprint
from middleware import authenticate, require_roles
from response import success_object
from services import core
from util import bump, filter_params, new_id, next_seq, paginate, req_string, sort_records

bp = Blueprint("guides", __name__)

SCORING_MODES = ["RAW", "LENIENCY_ADJUSTED"]
READ_ROLES = ["TalentAssessmentAdmin", "HiringManager", "Interviewer",
              "ComplianceOfficer", "DecisionOfficer"]


def _get_guide_or_404(gid):
    g = db.stores["guides"].get(gid)
    if g is None:
        raise err_not_found("InterviewGuide not found")
    return g


def validate_rubric(rubric_items):
    """Structural rubric checks (PRD §3.3). Returns normalized list."""
    if not isinstance(rubric_items, list):
        raise err_invalid_request("rubric_items must be an array")
    if len(rubric_items) < 2:
        raise api_err("ERR_RUBRIC_TOO_FEW_ITEMS", "rubric_items must contain at least 2 items")
    seen = set()
    normalized = []
    for item in rubric_items:
        if not isinstance(item, dict):
            raise err_invalid_request("rubric_items entries must be objects")
        code = item.get("competency_code")
        if not isinstance(code, str) or not code:
            raise err_invalid_request("competency_code is required")
        if code in seen:
            raise err_invalid_request("competency_code must be unique within the guide")
        seen.add(code)
        weight = item.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise err_invalid_request("weight must be a number")
        w = Decimal(str(weight))
        if w <= 0 or w > 1:
            raise err_invalid_request("weight must be in (0, 1]")
        scale_max = item.get("scale_max")
        if isinstance(scale_max, bool) or not isinstance(scale_max, int):
            raise err_invalid_request("scale_max must be an integer")
        if scale_max < 2 or scale_max > 10:
            raise err_invalid_request("scale_max must be between 2 and 10")
        normalized.append({
            "competency_code": code,
            "weight": weight,
            "scale_max": scale_max,
        })
    total = sum(Decimal(str(i["weight"])) for i in normalized)
    if total.quantize(Decimal("0.0001")) != Decimal("1.0000"):
        raise api_err("ERR_RUBRIC_WEIGHT_SUM",
                      "rubric weights must sum to exactly 1.0000 at 4dp")
    return normalized


def check_weight_sum(guide):
    total = sum(Decimal(str(i["weight"])) for i in guide["rubric_items"])
    if total.quantize(Decimal("0.0001")) != Decimal("1.0000"):
        raise api_err("ERR_RUBRIC_WEIGHT_SUM",
                      "rubric weights must sum to exactly 1.0000 at 4dp")


@bp.post("/talent/interview-guides")
def create_guide():
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    body = util.get_body()
    title = req_string(body, "title")
    rubric_items = validate_rubric(body.get("rubric_items"))
    mode = body.get("scoring_mode", "RAW")
    if mode not in SCORING_MODES:
        raise err_invalid_request("scoring_mode must be RAW | LENIENCY_ADJUSTED")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "supersedes_guide_id": None,
        "title": title,
        "status": "DRAFT",
        "rubric_items": rubric_items,
        "scoring_mode": mode,
        "version_label": 1,
        "superseded_by_guide_id": None,
        "created_by_user_id": ctx.user_id,
        "pinned_cycle_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["guides"][rec["id"]] = rec
    return success_object(serializers.guide(rec), 201)


@bp.post("/talent/interview-guides/<gid>/revisions")
def create_revision(gid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    target = _get_guide_or_404(gid)
    body = util.get_body()
    # OCC (tier 8) — non-optional field per PRD §2.6
    expected = body.get("expected_superseded_guide_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_superseded_guide_version is required")
    if expected != target["version"]:
        raise api_err("ERR_STALE_GUIDE_VERSION",
                      "expected_superseded_guide_version does not match current version")
    # target must be APPROVED (tier 9)
    if target["status"] != "APPROVED":
        raise api_err("ERR_GUIDE_NOT_APPROVED", "Supersede target must be APPROVED")
    title = req_string(body, "title")
    rubric_items = validate_rubric(body.get("rubric_items"))
    mode = body.get("scoring_mode", "RAW")
    if mode not in SCORING_MODES:
        raise err_invalid_request("scoring_mode must be RAW | LENIENCY_ADJUSTED")
    now = db.get_now()
    rec = {
        "id": new_id(),
        "supersedes_guide_id": gid,
        "title": title,
        "status": "DRAFT",
        "rubric_items": rubric_items,
        "scoring_mode": mode,
        "version_label": target["version_label"] + 1,
        "superseded_by_guide_id": None,
        "created_by_user_id": ctx.user_id,
        "pinned_cycle_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created": now,
        "_seq": next_seq(),
    }
    db.stores["guides"][rec["id"]] = rec
    # The supersede mutates the head: set superseded_by and bump its version.
    target["superseded_by_guide_id"] = rec["id"]
    bump(target)
    return success_object(serializers.guide(rec), 201)


@bp.get("/talent/interview-guides")
def list_guides():
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    filters = filter_params(["supersedes_guide_id", "status"])
    recs = []
    for g in sort_records(list(db.stores["guides"].values())):
        if "supersedes_guide_id" in filters and g["supersedes_guide_id"] != filters["supersedes_guide_id"]:
            continue
        if "status" in filters and g["status"] != filters["status"]:
            continue
        core.recompute_guide_pins(g)
        recs.append(serializers.guide(g))
    return paginate(recs)


@bp.get("/talent/interview-guides/<gid>")
def get_guide(gid):
    ctx = authenticate()
    require_roles(ctx, READ_ROLES)
    g = _get_guide_or_404(gid)
    core.recompute_guide_pins(g)
    return success_object(serializers.guide(g))


@bp.post("/talent/interview-guides/<gid>/pilot")
def pilot_guide(gid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    g = _get_guide_or_404(gid)
    if g["status"] != "DRAFT":
        raise api_err("ERR_INVALID_STATE", "Guide must be DRAFT to pilot")
    if len(g["rubric_items"]) < 2:
        raise api_err("ERR_RUBRIC_TOO_FEW_ITEMS", "rubric_items must contain at least 2 items")
    check_weight_sum(g)
    g["status"] = "PILOT"
    bump(g)
    return success_object(serializers.guide(g))


@bp.post("/talent/interview-guides/<gid>/retract")
def retract_guide(gid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    g = _get_guide_or_404(gid)
    if g["status"] != "PILOT":
        raise api_err("ERR_INVALID_STATE", "Guide must be PILOT to retract")
    g["status"] = "DRAFT"
    bump(g)
    return success_object(serializers.guide(g))


@bp.post("/talent/interview-guides/<gid>/approve")
def approve_guide(gid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    g = _get_guide_or_404(gid)
    if g["status"] != "PILOT":
        raise api_err("ERR_INVALID_STATE", "Guide must be PILOT to approve")
    check_weight_sum(g)
    # SoD: approver must differ from creator (tier 9)
    if ctx.user_id == g["created_by_user_id"]:
        raise api_err("ERR_SEGREGATION_OF_DUTIES",
                      "Guide approver must differ from the guide's creator")
    g["status"] = "APPROVED"
    bump(g)
    # Revision-chain cascade: retire the superseded APPROVED predecessor
    if g.get("supersedes_guide_id"):
        pred = db.stores["guides"].get(g["supersedes_guide_id"])
        if pred is not None and pred["status"] == "APPROVED":
            pred["status"] = "RETIRED"
            bump(pred)
            core.recompute_guide_pins(pred)
    core.recompute_guide_pins(g)
    return success_object(serializers.guide(g))


@bp.post("/talent/interview-guides/<gid>/retire")
def retire_guide(gid):
    ctx = authenticate()
    require_roles(ctx, ["TalentAssessmentAdmin"])
    g = _get_guide_or_404(gid)
    if g["status"] == "RETIRED":
        raise api_err("ERR_INVALID_STATE", "Guide already RETIRED")
    if g["status"] not in ("DRAFT", "PILOT", "APPROVED"):
        raise api_err("ERR_INVALID_STATE", "Guide cannot be retired from this state")
    core.recompute_guide_pins(g)
    if g["pinned_cycle_count"] != 0:
        raise api_err("ERR_GUIDE_PINNED", "Guide is pinned by non-CLOSED cycles")
    g["status"] = "RETIRED"
    bump(g)
    return success_object(serializers.guide(g))
