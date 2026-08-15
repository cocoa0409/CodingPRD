"""CompPlan and CptRate endpoints (PRD 3.1, 3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_PLAN_IMMUTABLE, ERR_PLAN_NOT_FMV_APPROVED, ERR_RATE_COVERAGE_INCOMPLETE,
    ERR_TIER_ORDER_INVALID, ERR_RATE_WINDOW_OVERLAP, ERR_SUCCESSOR_EXISTS,
    ERR_STALE_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch, public
from util import dec, decimal_places, parse_date_strict, CLOCK
from validate import (
    get_body, req_str, opt_str, req_int, opt_int, req_enum, opt_enum,
    req_date, req_number, require_path_resource, require_body_ref,
)

bp = Blueprint("plans", __name__)

PLAN_READ_ROLES = ["CompAnalyst", "CompCommittee", "ComplianceOfficer"]
MUTABLE_PLAN_STATUSES = ("DRAFT", "PENDING_REVIEW")
NON_TERMINAL_SUCCESSOR_STATUSES = ("DRAFT", "PENDING_REVIEW", "FMV_APPROVED")


def validate_tiers_payload(tiers):
    if not isinstance(tiers, list):
        raise_error(ERR_VALIDATION, "tiers must be an array")
    for t in tiers:
        if not isinstance(t, dict):
            raise_error(ERR_VALIDATION, "each tier must be an object")
        if not isinstance(t.get("tier_code"), str) or not t.get("tier_code"):
            raise_error(ERR_VALIDATION, "tier.tier_code must be a non-empty string")
        thr = t.get("threshold_wrvu")
        if isinstance(thr, bool) or not isinstance(thr, (int, float)):
            raise_error(ERR_VALIDATION, "tier.threshold_wrvu must be a number")
        cf = t.get("conversion_factor_cents")
        if isinstance(cf, bool) or not isinstance(cf, int):
            raise_error(ERR_VALIDATION, "tier.conversion_factor_cents must be an integer")
        tb = t.get("tier_bonus_cents")
        if isinstance(tb, bool) or not isinstance(tb, int):
            raise_error(ERR_VALIDATION, "tier.tier_bonus_cents must be an integer")
    return tiers


def check_tier_order(tiers):
    if len(tiers) < 1:
        raise_error(ERR_TIER_ORDER_INVALID, "at least one tier is required")
    if dec(tiers[0]["threshold_wrvu"]) != 0:
        raise_error(ERR_TIER_ORDER_INVALID, "first threshold_wrvu must be 0")
    prev = None
    for t in tiers:
        thr = dec(t["threshold_wrvu"])
        if prev is not None and thr <= prev:
            raise_error(ERR_TIER_ORDER_INVALID, "threshold_wrvu values must be strictly increasing")
        prev = thr


def _has_rate_row(plan_id):
    return any(r["plan_id"] == plan_id for r in db["cpt_rates"].values())


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

@bp.post("/comp-plans")
def create_plan():
    authorized(["CompAnalyst"])
    body = get_body()
    # Priority 4: body FK existence (when the field is present and well-typed)
    supersedes = body.get("supersedes_plan_id")
    sup_plan = require_body_ref("comp_plans", supersedes, "supersedes_plan_id")
    # Priority 14: payload shape
    name = req_str(body, "name")
    fys = req_date(body, "fiscal_year_start")
    fye = req_date(body, "fiscal_year_end")
    if parse_date_strict(fye) <= parse_date_strict(fys):
        raise_error(ERR_VALIDATION, "fiscal_year_end must be after fiscal_year_start")
    cam = opt_enum(body, "credit_attribution_mode", {"SERVICE_DATE", "POSTING_DATE"}, "SERVICE_DATE")
    qm = opt_enum(body, "quality_model", {"ALL_OR_NOTHING", "SLIDING_SCALE"}, "ALL_OR_NOTHING")
    if "tiers" not in body or body.get("tiers") is None:
        raise_error(ERR_VALIDATION, "tiers is required")
    tiers = validate_tiers_payload(body.get("tiers"))
    quality_pool_cents = req_int(body, "quality_pool_cents", non_negative=True)
    fmv_cap_cents = req_int(body, "fmv_cap_cents", positive=True)
    if supersedes is not None and not isinstance(supersedes, str):
        raise_error(ERR_VALIDATION, "supersedes_plan_id must be a string")
    if sup_plan is not None and sup_plan["status"] != "ACTIVE":
        raise_error(ERR_VALIDATION, "supersedes_plan_id must reference an ACTIVE plan")
    # Priority 15: tier ordering
    check_tier_order(tiers)
    # Priority 17: at most one non-terminal successor per superseded plan
    if supersedes is not None:
        for p in db["comp_plans"].values():
            if (p["supersedes_plan_id"] == supersedes
                    and p["status"] in NON_TERMINAL_SUCCESSOR_STATUSES):
                raise_error(ERR_SUCCESSOR_EXISTS,
                            "a non-terminal successor plan already exists for this plan")
    rec = new_record("comp_plans", {
        "name": name,
        "fiscal_year_start": fys,
        "fiscal_year_end": fye,
        "credit_attribution_mode": cam,
        "quality_model": qm,
        "tiers": tiers,
        "quality_pool_cents": quality_pool_cents,
        "fmv_cap_cents": fmv_cap_cents,
        "supersedes_plan_id": supersedes,
        "status": "DRAFT",
        "activated_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/comp-plans/<rid>")
def get_plan(rid):
    authorized(PLAN_READ_ROLES)
    plan = require_path_resource("comp_plans", rid)
    return success_object(public(plan))


@bp.get("/comp-plans/<rid>/successor-plans")
def list_successor_plans(rid):
    authorized(PLAN_READ_ROLES)
    require_path_resource("comp_plans", rid)
    return list_response("comp_plans", {"supersedes_plan_id": rid})


@bp.put("/comp-plans/<rid>")
def update_plan(rid):
    authorized(["CompAnalyst"])
    plan = require_path_resource("comp_plans", rid)
    # Priority 6: immutability once the plan leaves DRAFT/PENDING_REVIEW
    if plan["status"] not in MUTABLE_PLAN_STATUSES:
        raise_error(ERR_PLAN_IMMUTABLE,
                    "plan configuration is mutable only while DRAFT or PENDING_REVIEW")
    body = get_body()
    # Priority 14: payload shape
    expected = req_int(body, "expected_comp_plan_version")
    name = opt_str(body, "name")
    cam = opt_enum(body, "credit_attribution_mode", {"SERVICE_DATE", "POSTING_DATE"})
    qm = opt_enum(body, "quality_model", {"ALL_OR_NOTHING", "SLIDING_SCALE"})
    tiers = None
    if "tiers" in body and body.get("tiers") is not None:
        tiers = validate_tiers_payload(body.get("tiers"))
    quality_pool_cents = opt_int(body, "quality_pool_cents", non_negative=True)
    fmv_cap_cents = opt_int(body, "fmv_cap_cents", positive=True)
    # OCC (concurrency rule plan-update-stale-version)
    if expected != plan["version"]:
        raise_error(ERR_STALE_VERSION, "plan version has advanced since it was observed")
    # Priority 15: tier ordering (only when tiers are being replaced)
    if tiers is not None:
        check_tier_order(tiers)
    for field, value in (("name", name), ("credit_attribution_mode", cam),
                         ("quality_model", qm), ("tiers", tiers),
                         ("quality_pool_cents", quality_pool_cents),
                         ("fmv_cap_cents", fmv_cap_cents)):
        if value is not None:
            plan[field] = value
    touch("comp_plans", plan)
    return success_object(public(plan))


@bp.post("/comp-plans/<rid>/submit-review")
def submit_plan_review(rid):
    authorized(["CompAnalyst"])
    plan = require_path_resource("comp_plans", rid)
    if plan["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT plan can be submitted for review")
    if not _has_rate_row(plan["id"]):
        raise_error(ERR_RATE_COVERAGE_INCOMPLETE, "plan has no CptRate rows")
    plan["status"] = "PENDING_REVIEW"
    touch("comp_plans", plan)
    return success_object(public(plan))


@bp.post("/comp-plans/<rid>/review-decision")
def plan_review_decision(rid):
    authorized(["ComplianceOfficer"])
    plan = require_path_resource("comp_plans", rid)
    if plan["status"] != "PENDING_REVIEW":
        raise_error(ERR_INVALID_STATE, "plan is not PENDING_REVIEW")
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVED", "REJECTED"})
    plan["status"] = "FMV_APPROVED" if decision == "APPROVED" else "DRAFT"
    touch("comp_plans", plan)
    return success_object(public(plan))


@bp.post("/comp-plans/<rid>/activate")
def activate_plan(rid):
    authorized(["CompCommittee"])
    plan = require_path_resource("comp_plans", rid)
    if plan["status"] != "FMV_APPROVED":
        raise_error(ERR_PLAN_NOT_FMV_APPROVED, "plan activation requires FMV_APPROVED status")
    if not _has_rate_row(plan["id"]):
        raise_error(ERR_RATE_COVERAGE_INCOMPLETE, "plan has no CptRate rows")
    plan["status"] = "ACTIVE"
    plan["activated_at"] = CLOCK.now_iso()
    touch("comp_plans", plan)
    return success_object(public(plan))


@bp.post("/comp-plans/<rid>/close")
def close_plan(rid):
    authorized(["CompCommittee"])
    plan = require_path_resource("comp_plans", rid)
    if plan["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE plan can be closed")
    for a in db["physician_agreements"].values():
        if a["plan_id"] == plan["id"] and a["status"] in (
                "DRAFT", "PENDING_FMV", "FMV_APPROVED", "EFFECTIVE", "AMENDMENT_REQUIRED"):
            raise_error(ERR_INVALID_STATE,
                        "plan has non-terminal agreements and cannot be closed")
    plan["status"] = "CLOSED"
    touch("comp_plans", plan)
    return success_object(public(plan))


# ---------------------------------------------------------------------------
# CptRate rows
# ---------------------------------------------------------------------------

@bp.post("/comp-plans/<rid>/cpt-rates")
def create_cpt_rate(rid):
    authorized(["CompAnalyst"])
    plan = require_path_resource("comp_plans", rid)
    # Priority 6: immutability precedes the overlap check (PRD 3.1)
    if plan["status"] not in MUTABLE_PLAN_STATUSES:
        raise_error(ERR_PLAN_IMMUTABLE, "rate rows are mutable only while the plan is DRAFT or PENDING_REVIEW")
    body = get_body()
    # Priority 14: payload shape
    cpt_code = req_str(body, "cpt_code")
    wrvu_value = req_number(body, "wrvu_value")
    if dec(wrvu_value) < 0:
        raise_error(ERR_VALIDATION, "wrvu_value must be >= 0")
    if decimal_places(wrvu_value) > 3:
        raise_error(ERR_VALIDATION, "wrvu_value may carry up to 3 decimal places")
    effective_from = req_date(body, "effective_from")
    effective_to = req_date(body, "effective_to")
    f_from = parse_date_strict(effective_from)
    f_to = parse_date_strict(effective_to)
    if f_to <= f_from:
        raise_error(ERR_VALIDATION, "effective_to must be strictly after effective_from")
    # Priority 16: half-open window overlap per (plan, cpt_code); adjacency allowed
    for r in db["cpt_rates"].values():
        if r["plan_id"] != plan["id"] or r["cpt_code"] != cpt_code:
            continue
        r_from = parse_date_strict(r["effective_from"])
        r_to = parse_date_strict(r["effective_to"])
        if f_from < r_to and r_from < f_to:
            raise_error(ERR_RATE_WINDOW_OVERLAP,
                        "rate window overlaps an existing row for this CPT code")
    rec = new_record("cpt_rates", {
        "plan_id": plan["id"],
        "cpt_code": cpt_code,
        "wrvu_value": wrvu_value,
        "effective_from": effective_from,
        "effective_to": effective_to,
    })
    return success_object(public(rec), status=201)


@bp.get("/comp-plans/<rid>/cpt-rates")
def list_cpt_rates(rid):
    authorized(PLAN_READ_ROLES)
    require_path_resource("comp_plans", rid)
    filters = {"plan_id": rid, "cpt_code": request.args.get("cpt_code")}
    return list_response("cpt_rates", filters)


@bp.delete("/cpt-rates/<rid>")
def delete_cpt_rate(rid):
    authorized(["CompAnalyst"])
    rate = require_path_resource("cpt_rates", rid)
    plan = db["comp_plans"].get(rate["plan_id"])
    if plan is not None and plan["status"] not in MUTABLE_PLAN_STATUSES:
        raise_error(ERR_PLAN_IMMUTABLE, "rate rows are mutable only while the plan is DRAFT or PENDING_REVIEW")
    del db["cpt_rates"][rid]
    return "", 204
